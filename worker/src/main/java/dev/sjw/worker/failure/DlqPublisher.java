package dev.sjw.worker.failure;

import dev.sjw.common.queue.QueueKeys;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/** DLQ 적재 — 실패 사유가 분류된 채로 쌓인다 (M2 수용 기준). */
@Component
public class DlqPublisher {

    private static final Logger log = LoggerFactory.getLogger(DlqPublisher.class);

    private final StringRedisTemplate redis;

    public DlqPublisher(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public void publish(UUID jobId, ErrorClass errorClass, String message) {
        redis.opsForStream().add(StreamRecords.newRecord()
                .in(QueueKeys.DLQ)
                .ofMap(Map.of(
                        QueueKeys.FIELD_JOB_ID, jobId.toString(),
                        "errorClass", errorClass.name(),
                        "message", message == null ? "" : message.substring(0, Math.min(400, message.length())),
                        "failedAt", OffsetDateTime.now().toString())));
        log.warn("DLQ 적재: job={}, class={}", jobId, errorClass);
    }
}
