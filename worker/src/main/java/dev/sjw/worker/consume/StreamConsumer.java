package dev.sjw.worker.consume;

import dev.sjw.common.queue.QueueKeys;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;
import org.springframework.data.redis.RedisSystemException;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.PendingMessage;
import org.springframework.data.redis.connection.stream.PendingMessages;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.RedisStreamCommands.XClaimOptions;
import org.springframework.stereotype.Component;

/**
 * Redis Streams Consumer Group 소비 루프 (§8.3).
 * - 메시지 = jobId만. 본문·상태는 Postgres.
 * - 처리 성공/스킵 시에만 XACK. 처리 중 프로세스가 죽으면 pending으로 남고,
 *   재기동 시 claimStale()이 회수해 이어서 처리한다 (체크포인트의 큐 측 절반).
 */
@Component
public class StreamConsumer implements SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(StreamConsumer.class);
    private static final Duration POLL_BLOCK = Duration.ofSeconds(2);
    private static final Duration STALE_MIN_IDLE = Duration.ofSeconds(30);

    private final StringRedisTemplate redis;
    private final JobProcessor processor;
    private final long paceMs;
    private final String consumerName = "worker-" + ProcessHandle.current().pid();

    private volatile boolean running = false;
    private Thread thread;
    private long loops = 0;

    public StreamConsumer(StringRedisTemplate redis, JobProcessor processor,
                          @org.springframework.beans.factory.annotation.Value("${sjw.worker.pace-ms:3000}")
                          long paceMs) {
        this.redis = redis;
        this.processor = processor;
        this.paceMs = paceMs;
    }

    @Override
    public void start() {
        ensureGroup();
        running = true;
        thread = new Thread(this::loop, "stream-consumer");
        thread.start();
        log.info("소비 시작: stream={}, group={}, consumer={}",
                QueueKeys.STREAM, QueueKeys.CONSUMER_GROUP, consumerName);
    }

    private void ensureGroup() {
        try {
            redis.execute((org.springframework.data.redis.core.RedisCallback<Void>) conn -> {
                conn.streamCommands().xGroupCreate(
                        QueueKeys.STREAM.getBytes(), QueueKeys.CONSUMER_GROUP,
                        ReadOffset.from("0"), true /* MKSTREAM */);
                return null;
            });
        } catch (RedisSystemException e) {
            if (e.getCause() != null && String.valueOf(e.getCause().getMessage()).contains("BUSYGROUP")) {
                return; // 이미 존재
            }
            throw e;
        }
    }

    private void loop() {
        claimStale(); // 재기동 직후: 죽은 소비자의 미ACK 메시지 회수
        while (running) {
            try {
                List<MapRecord<String, Object, Object>> records = redis.opsForStream().read(
                        Consumer.from(QueueKeys.CONSUMER_GROUP, consumerName),
                        StreamReadOptions.empty().count(1).block(POLL_BLOCK),
                        StreamOffset.create(QueueKeys.STREAM, ReadOffset.lastConsumed()));
                if (records != null) {
                    for (MapRecord<String, Object, Object> r : records) {
                        handle(r);
                    }
                }
                if (++loops % 30 == 0) {
                    claimStale(); // 주기 회수 (약 1분 간격)
                }
            } catch (Exception e) {
                if (running) {
                    log.error("소비 루프 오류 — 2초 후 재시도: {}", e.toString());
                    sleep(2000);
                }
            }
        }
    }

    private void handle(MapRecord<String, Object, Object> record) {
        Object raw = record.getValue().get(QueueKeys.FIELD_JOB_ID);
        boolean ack;
        try {
            ack = processor.process(UUID.fromString(String.valueOf(raw)));
        } catch (Exception e) {
            log.error("메시지 {} 처리 예외 — 미ACK(재전달 대상): {}", record.getId(), e.toString());
            return;
        }
        if (ack) {
            redis.opsForStream().acknowledge(QueueKeys.STREAM, QueueKeys.CONSUMER_GROUP, record.getId());
        }
        // 임시 고정 페이싱 (무료 티어 RPM 보호). S5에서 적응형 토큰 버킷으로 대체된다.
        sleep(paceMs);
    }

    /** 30초 이상 idle인 pending 메시지를 내 소유로 claim해 재처리한다. */
    private void claimStale() {
        try {
            PendingMessages pending = redis.opsForStream().pending(
                    QueueKeys.STREAM, QueueKeys.CONSUMER_GROUP, Range.unbounded(), 50);
            if (pending == null || pending.isEmpty()) {
                return;
            }
            List<RecordId> stale = pending.stream()
                    .filter(p -> p.getElapsedTimeSinceLastDelivery().compareTo(STALE_MIN_IDLE) > 0)
                    .map(PendingMessage::getId)
                    .toList();
            if (stale.isEmpty()) {
                return;
            }
            List<MapRecord<String, Object, Object>> claimed = redis.opsForStream().claim(
                    QueueKeys.STREAM, QueueKeys.CONSUMER_GROUP, consumerName,
                    XClaimOptions.minIdle(STALE_MIN_IDLE).ids(stale.toArray(new RecordId[0])));
            log.info("stale {}건 claim — 이어서 처리", claimed.size());
            for (MapRecord<String, Object, Object> r : claimed) {
                handle(r);
            }
        } catch (Exception e) {
            log.warn("claimStale 실패 (다음 주기 재시도): {}", e.toString());
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public void stop() {
        running = false;
        if (thread != null) {
            try {
                thread.join(3000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }

    @Override
    public boolean isRunning() {
        return running;
    }
}
