package dev.sjw.worker.batch;

import dev.sjw.common.job.BatchJobRepository;
import dev.sjw.common.job.BatchRow;
import dev.sjw.common.job.CostLedgerRepository;
import dev.sjw.common.queue.QueueKeys;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 배치 발행 펌프: RUNNING 배치의 커서부터 소량 윈도우로 스트림에 발행한다.
 * - 일시정지 = 발행 중단 (인플라이트는 자연 완료). 재개 = 커서부터 계속.
 * - 예산 강제: 원장(cost_ledger) 실측 호출 수 >= budget_limit_calls → BUDGET_EXHAUSTED.
 * - 중복 발행이 나도 JobProcessor의 SUCCEEDED 스킵이 중복 LLM 호출을 막는다.
 */
@Component
public class BatchPump {

    private static final Logger log = LoggerFactory.getLogger(BatchPump.class);
    private static final int WINDOW = 3; // 동시 인플라이트 상한 (무료 RPM 보호)

    private final BatchJobRepository batches;
    private final CostLedgerRepository ledger;
    private final StringRedisTemplate redis;

    public BatchPump(BatchJobRepository batches, CostLedgerRepository ledger,
                     StringRedisTemplate redis) {
        this.batches = batches;
        this.ledger = ledger;
        this.redis = redis;
    }

    @Scheduled(fixedDelay = 1000)
    public void pump() {
        for (BatchRow b : batches.findByStatus("RUNNING")) {
            try {
                pumpOne(b);
            } catch (Exception e) {
                log.error("batch {} 펌프 오류: {}", b.id(), e.toString());
            }
        }
    }

    private void pumpOne(BatchRow b) {
        int[] t = batches.terminalCounts(b.id());
        int done = t[0], failed = t[1], terminal = done + failed;

        if (terminal >= b.totalCount()) {
            batches.updateProgress(b.id(), b.cursorCheckpoint(), done, failed);
            batches.transition(b.id(), "RUNNING", "COMPLETED");
            log.info("batch {} 완료: 성공 {}, 실패 {}", b.id(), done, failed);
            return;
        }

        long spentCalls = ledger.countCallsForBatch(b.id());
        if (spentCalls >= b.budgetLimitCalls()) {
            batches.updateProgress(b.id(), b.cursorCheckpoint(), done, failed);
            batches.transition(b.id(), "RUNNING", "BUDGET_EXHAUSTED");
            log.warn("batch {} 예산 소진: 호출 {} / 한도 {}", b.id(), spentCalls, b.budgetLimitCalls());
            return;
        }

        int cursor = b.cursorCheckpoint();
        int inFlight = cursor - terminal;
        while (inFlight < WINDOW && cursor < b.totalCount()
                && spentCalls + inFlight < b.budgetLimitCalls()) {
            UUID jobId = batches.jobIdByIndex(b.id(), cursor).orElse(null);
            if (jobId == null) {
                log.error("batch {} index {} job 없음 — 건너뜀", b.id(), cursor);
                cursor++;
                continue;
            }
            redis.opsForStream().add(StreamRecords.newRecord()
                    .in(QueueKeys.STREAM)
                    .ofMap(Map.of(QueueKeys.FIELD_JOB_ID, jobId.toString())));
            cursor++;
            inFlight++;
        }
        batches.updateProgress(b.id(), cursor, done, failed);
    }
}
