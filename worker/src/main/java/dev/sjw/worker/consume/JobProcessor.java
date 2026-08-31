package dev.sjw.worker.consume;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.common.job.CostLedgerRepository;
import dev.sjw.common.job.JobRow;
import dev.sjw.common.job.JobStatus;
import dev.sjw.common.job.TranslationJobRepository;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationService;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 파이프라인 실행 단위. 멱등 규칙:
 *  - SUCCEEDED/DEAD면 즉시 스킵 → 재전달·재기동 시 중복 LLM 호출 0건 (M2 수용 기준)
 *  - LLM 호출이 실제 발생한 직후 cost_ledger에 1행 기록 → "호출 수"의 원장
 */
@Component
public class JobProcessor {

    private static final Logger log = LoggerFactory.getLogger(JobProcessor.class);
    private static final ObjectMapper JSON = new ObjectMapper();

    private final TranslationJobRepository jobs;
    private final CostLedgerRepository ledger;
    private final TranslationService translationService;

    public JobProcessor(TranslationJobRepository jobs, CostLedgerRepository ledger,
                        TranslationService translationService) {
        this.jobs = jobs;
        this.ledger = ledger;
        this.translationService = translationService;
    }

    /** @return true면 ACK 대상 (완료·스킵·영구 실패), false면 미ACK — 재전달로 재시도 */
    public boolean process(UUID jobId) {
        JobRow job = jobs.findById(jobId).orElse(null);
        if (job == null) {
            log.warn("job {} 없음 — ACK 후 폐기", jobId);
            return true;
        }
        if (job.status() == JobStatus.SUCCEEDED || job.status() == JobStatus.DEAD) {
            log.info("job {} 이미 {} — 스킵 (멱등)", jobId, job.status());
            return true;
        }
        // RUNNING 재진입 허용: 스트림 소유권(claim)이 동시 실행을 막아주므로,
        // 결과 저장 전에 죽은 RUNNING 잔재는 여기서 재실행된다.
        jobs.tryMarkRunning(jobId);

        try {
            TranslationResponse resp = translationService.translate(job.sourceText(), job.docYear());
            ledger.record(jobId, resp.meta().model(),
                    resp.meta().tokensIn(), resp.meta().tokensOut());
            jobs.insertResult(jobId, resp.translatedText(),
                    JSON.writeValueAsString(resp.entities()),
                    JSON.writeValueAsString(resp.uncertainSpans()));
            jobs.markSucceeded(jobId, resp.meta().model(), null /* cacheHit — M3 */,
                    resp.meta().tokensIn(), resp.meta().tokensOut(), resp.meta().kbVersion());
            log.info("job {} 완료 (llm {}ms)", jobId, resp.meta().latencyMs().get("llm"));
            return true;
        } catch (Exception e) {
            // S4에서 실패 분류기(SPEND_CAP/QUOTA_DAILY/RATE_LIMITED/…)로 교체된다.
            log.error("job {} 실패: {}", jobId, e.toString());
            jobs.markFailed(jobId, JobStatus.FAILED, e.getClass().getSimpleName());
            return true;
        }
    }
}
