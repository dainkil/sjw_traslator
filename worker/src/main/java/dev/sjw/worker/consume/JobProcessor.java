package dev.sjw.worker.consume;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.common.job.BatchJobRepository;
import dev.sjw.common.job.CostLedgerRepository;
import dev.sjw.common.job.JobRow;
import dev.sjw.common.job.JobStatus;
import dev.sjw.common.job.TranslationJobRepository;
import dev.sjw.common.translate.LlmParseException;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationService;
import dev.sjw.worker.failure.DlqPublisher;
import dev.sjw.worker.failure.ErrorClass;
import dev.sjw.worker.failure.FailureClassifier;
import dev.sjw.worker.rate.AdaptiveRateLimiter;
import dev.sjw.worker.rate.RateLimitWaitTimeoutException;
import dev.sjw.worker.rate.RetryAfterHint;
import io.github.resilience4j.circuitbreaker.CallNotPermittedException;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import io.github.resilience4j.core.IntervalFunction;
import io.github.resilience4j.retry.Retry;
import io.github.resilience4j.retry.RetryConfig;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.Callable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 파이프라인 실행 + 실패 분류 정책 (§6).
 *
 * 멱등: SUCCEEDED/DEAD 스킵 + LLM 호출마다 cost_ledger 1행 (파싱 실패로 버려진 호출 포함 —
 * 과금은 파싱 성공 여부와 무관하게 발생했으므로).
 *
 * 내결함성 (계획서 D6):
 *  - Resilience4j Retry: transient(순간 429/5xx/타임아웃/파싱)만 즉시 1회 재시도, 지수 backoff + jitter.
 *    (Spring AI 내장 재시도는 yml에서 1회로 꺼서 이중 재시도를 막는다)
 *  - CircuitBreaker: 연속 장애 시 open → 호출 단락, 메시지는 미ACK 재전달로 자연 백오프.
 *  - AdaptiveRateLimiter: 호출 직전 permit 획득(페이싱), 429는 rate 하향 피드백으로 되먹인다 (ADR-017).
 *    재시도마다 permit을 다시 얻어야 하므로 리미터는 Retry 안쪽에 들어간다.
 */
@Component
public class JobProcessor {

    /** ACK 여부 결정용 처리 결과 */
    public enum Outcome { ACK, REDELIVER }

    private static final Logger log = LoggerFactory.getLogger(JobProcessor.class);
    private static final ObjectMapper JSON = new ObjectMapper();

    private final TranslationJobRepository jobs;
    private final CostLedgerRepository ledger;
    private final BatchJobRepository batches;
    private final TranslationService translationService;
    private final FailureClassifier classifier;
    private final DlqPublisher dlq;
    private final AdaptiveRateLimiter rateLimiter;
    private final Retry retry;
    private final CircuitBreaker breaker;

    public JobProcessor(TranslationJobRepository jobs, CostLedgerRepository ledger,
                        BatchJobRepository batches, TranslationService translationService,
                        FailureClassifier classifier, DlqPublisher dlq,
                        AdaptiveRateLimiter rateLimiter) {
        this.jobs = jobs;
        this.ledger = ledger;
        this.batches = batches;
        this.translationService = translationService;
        this.classifier = classifier;
        this.dlq = dlq;
        this.rateLimiter = rateLimiter;
        this.retry = Retry.of("llm", RetryConfig.custom()
                .maxAttempts(2)
                .intervalFunction(IntervalFunction.ofExponentialRandomBackoff(
                        Duration.ofSeconds(2), 2.0, 0.5))
                .retryOnException(e -> {
                    if (e instanceof RateLimitWaitTimeoutException) {
                        return false; // 아직 호출조차 못 함 — 재시도가 아니라 재전달로 넘긴다
                    }
                    ErrorClass c = classifier.classify(e);
                    // QUOTA_DAILY/SPEND_CAP은 즉시 재시도해봐야 quota만 두드린다 — 재시도 금지
                    return c.transientRetry() && c != ErrorClass.PARSE_ERROR;
                })
                .build());
        this.breaker = CircuitBreaker.of("llm", CircuitBreakerConfig.custom()
                .slidingWindowSize(10)
                .failureRateThreshold(50)
                .waitDurationInOpenState(Duration.ofSeconds(30))
                .ignoreException(e -> {
                    if (e instanceof RateLimitWaitTimeoutException) {
                        return true; // provider 건강과 무관 (우리 쪽 페이싱)
                    }
                    ErrorClass c = classifier.classify(e);
                    // 영구 오류(파싱·필터·quota)는 provider 건강과 무관 — 브레이커 통계에서 제외
                    return c == ErrorClass.PARSE_ERROR || c == ErrorClass.CONTENT_FILTERED
                            || c == ErrorClass.QUOTA_DAILY || c == ErrorClass.SPEND_CAP;
                })
                .build());
    }

    public Outcome process(UUID jobId, long deliveryCount) {
        JobRow job = jobs.findById(jobId).orElse(null);
        if (job == null) {
            log.warn("job {} 없음 — ACK 후 폐기", jobId);
            return Outcome.ACK;
        }
        if (job.status() == JobStatus.SUCCEEDED || job.status() == JobStatus.DEAD) {
            log.info("job {} 이미 {} — 스킵 (멱등)", jobId, job.status());
            return Outcome.ACK;
        }
        jobs.tryMarkRunning(jobId);

        String model = translationService.model();
        Callable<TranslationResponse> guarded = () -> {
            rateLimiter.acquire(model); // 버킷이 비어 있으면 여기서 대기 — 이것이 워커의 페이싱이다
            try {
                TranslationResponse r = translationService.translate(job.sourceText(), job.docYear());
                rateLimiter.onSuccess(model);
                return r;
            } catch (Exception e) {
                if (classifier.classify(e) == ErrorClass.RATE_LIMITED) {
                    // 재시도 전에 rate를 먼저 내린다 — 같은 속도로 재시도하면 429만 더 맞는다
                    rateLimiter.onRateLimited(model, RetryAfterHint.parse(e).orElse(null));
                }
                throw e;
            }
        };
        Callable<TranslationResponse> call = CircuitBreaker.decorateCallable(breaker,
                Retry.decorateCallable(retry, guarded));
        try {
            TranslationResponse resp = call.call();
            ledger.record(jobId, resp.meta().model(),
                    resp.meta().tokensIn(), resp.meta().tokensOut());
            jobs.insertResult(jobId, resp.translatedText(),
                    JSON.writeValueAsString(resp.entities()),
                    JSON.writeValueAsString(resp.uncertainSpans()));
            jobs.markSucceeded(jobId, resp.meta().model(), null /* cacheHit — M3 */,
                    resp.meta().tokensIn(), resp.meta().tokensOut(), resp.meta().kbVersion());
            return Outcome.ACK;
        } catch (RateLimitWaitTimeoutException wait) {
            log.warn("job {} permit 대기 상한 — 미ACK 재전달: {}", jobId, wait.getMessage());
            return Outcome.REDELIVER;
        } catch (CallNotPermittedException open) {
            log.warn("서킷 open — job {} 미ACK 재전달 (자연 백오프)", jobId);
            return Outcome.REDELIVER;
        } catch (Exception e) {
            return onFailure(job, e, deliveryCount);
        }
    }

    private Outcome onFailure(JobRow job, Exception e, long deliveryCount) {
        ErrorClass c = classifier.classify(e);
        log.error("job {} 실패[{}] (delivery {}): {}", job.id(), c, deliveryCount, brief(e));

        // 파싱 실패도 호출은 발생 — 원장에 기록 (과금 회계 정확성)
        LlmParseException pe = e instanceof LlmParseException p ? p
                : (e.getCause() instanceof LlmParseException p2 ? p2 : null);
        if (pe != null) {
            ledger.record(job.id(), pe.model(), pe.tokensIn(), pe.tokensOut());
        }

        if (c.deadImmediately()) {
            jobs.markFailed(job.id(), JobStatus.DEAD, c.name());
            dlq.publish(job.id(), c, brief(e));
            pauseBatchIfNeeded(job, c);
            return Outcome.ACK;
        }
        if (c == ErrorClass.QUOTA_DAILY) {
            // 오늘은 회복 불가. job은 FAILED로 남겨 내일 resume 시 재발행 (재시도 경로),
            // 배치는 자동 일시정지 — quota가 남은 다른 배치/모델을 위해 하늘에 헛방 안 쏨.
            jobs.markFailed(job.id(), JobStatus.FAILED, c.name());
            pauseBatchIfNeeded(job, c);
            return Outcome.ACK;
        }
        if (deliveryCount >= 4) {
            jobs.markFailed(job.id(), JobStatus.DEAD, c.name() + "_MAX_REDELIVERY");
            dlq.publish(job.id(), c, "재전달 상한 초과: " + brief(e));
            return Outcome.ACK;
        }
        // transient: FAILED 기록 후 미ACK — claim 주기(30초+)가 자연 백오프가 된다
        jobs.markFailed(job.id(), JobStatus.FAILED, c.name());
        return Outcome.REDELIVER;
    }

    private void pauseBatchIfNeeded(JobRow job, ErrorClass c) {
        if (job.batchId() != null && (c == ErrorClass.QUOTA_DAILY || c == ErrorClass.SPEND_CAP)) {
            batches.transition(job.batchId(), "RUNNING", "QUOTA_PAUSED");
            log.warn("batch {} 자동 일시정지 ({})", job.batchId(), c);
        }
    }

    private static String brief(Throwable e) {
        Throwable root = e;
        while (root.getCause() != null && root.getCause() != root) {
            root = root.getCause();
        }
        String m = String.valueOf(root.getMessage());
        return root.getClass().getSimpleName() + ": " + m.substring(0, Math.min(200, m.length()));
    }
}
