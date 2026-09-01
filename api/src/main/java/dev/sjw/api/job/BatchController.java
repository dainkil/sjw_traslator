package dev.sjw.api.job;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.api.tenant.TenantGuard;
import dev.sjw.common.job.BatchJobRepository;
import dev.sjw.common.job.BatchRow;
import dev.sjw.common.job.TranslationJobRepository;
import dev.sjw.common.util.TextHash;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import java.io.File;
import java.io.IOException;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 배치 API (§8.1). budget_limit(호출 수) 필수 — 생성 시 사전 검증(§5.3).
 * job 행은 생성 시 전부 만들고, 발행은 Worker의 BatchPump가 커서부터 진행한다.
 */
@RestController
@RequestMapping("/api/v1/batches")
public class BatchController {

    private static final ObjectMapper JSON = new ObjectMapper();

    private final BatchJobRepository batches;
    private final TranslationJobRepository jobs;
    private final org.springframework.data.redis.core.StringRedisTemplate redisForBatch;
    private final TenantGuard tenantGuard;
    private final String corpusPath;

    public BatchController(BatchJobRepository batches, TranslationJobRepository jobs,
                           org.springframework.data.redis.core.StringRedisTemplate redisForBatch,
                           TenantGuard tenantGuard,
                           @Value("${sjw.eval.corpus:../eval/eval300_1925.json}") String corpusPath) {
        this.batches = batches;
        this.jobs = jobs;
        this.redisForBatch = redisForBatch;
        this.tenantGuard = tenantGuard;
        this.corpusPath = corpusPath;
    }

    public record CreateBatch(
            @NotNull @Min(0) Integer offset,
            @NotNull @Min(1) @Max(300) Integer limit,
            @NotNull @Min(1) Integer budgetLimitCalls
    ) {}

    public record BatchView(UUID batchId, String status, int total, int done, int failed,
                            int cursor, int budgetLimitCalls) {}

    @PostMapping
    public ResponseEntity<?> create(@Valid @RequestBody CreateBatch req,
                                    @org.springframework.web.bind.annotation.RequestHeader(value = "X-Api-Key", required = false)
                                    String apiKey) throws IOException {
        var tenant = tenantGuard.resolve(apiKey);
        // 예산 사전 검증: 예상 호출 수(=limit, 캐시 0% 가정)가 예산을 넘으면 시작 전에 거부 (§5.3)
        if (req.limit() > req.budgetLimitCalls()) {
            return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(java.util.Map.of(
                    "error", "BUDGET_INSUFFICIENT",
                    "estimatedCalls", req.limit(),
                    "budgetLimitCalls", req.budgetLimitCalls()));
        }
        JsonNode corpus = JSON.readTree(new File(corpusPath)).get("corpus");
        if (req.offset() + req.limit() > corpus.size()) {
            return ResponseEntity.badRequest().body(java.util.Map.of(
                    "error", "RANGE_OUT_OF_BOUNDS", "corpusSize", corpus.size()));
        }

        tenantGuard.charge(tenant, req.limit()); // 배치는 job 수만큼 선과금
        UUID batchId = UUID.randomUUID();
        String rangeSpec = JSON.writeValueAsString(java.util.Map.of(
                "source", "eval300_1925", "offset", req.offset(), "limit", req.limit()));
        batches.insert(batchId, rangeSpec, req.budgetLimitCalls(), req.limit(), tenant.id());

        for (int i = 0; i < req.limit(); i++) {
            JsonNode item = corpus.get(req.offset() + i);
            String text = item.get("original").asText();
            Integer year = reignYearToAd(item.get("id").asText());
            jobs.insertPending(UUID.randomUUID(), BatchJobRepository.batchKey(batchId, i),
                    text, year, TextHash.normalizedHash(text), batchId, tenant.id());
        }
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(new BatchView(batchId, "RUNNING", req.limit(), 0, 0, 0, req.budgetLimitCalls()));
    }

    @GetMapping("/{id}")
    public ResponseEntity<BatchView> get(@PathVariable UUID id) {
        return batches.findById(id)
                .map(b -> ResponseEntity.ok(view(b)))
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping("/{id}/pause")
    public ResponseEntity<?> pause(@PathVariable UUID id) {
        boolean ok = batches.transition(id, "RUNNING", "PAUSED");
        return ok ? ResponseEntity.ok(java.util.Map.of("status", "PAUSED"))
                : ResponseEntity.status(HttpStatus.CONFLICT).body(java.util.Map.of("error", "NOT_RUNNING"));
    }

    @PostMapping("/{id}/resume")
    public ResponseEntity<?> resume(@PathVariable UUID id) {
        boolean ok = batches.transition(id, "PAUSED", "RUNNING")
                || batches.transition(id, "QUOTA_PAUSED", "RUNNING");
        if (!ok) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(java.util.Map.of("error", "NOT_PAUSED"));
        }
        // FAILED(예: 일일 quota로 막혔던) job을 재시도 대상으로 되돌리고 재발행
        var retried = jobs.resetFailedToPending(id);
        retried.forEach(this::publishJob);
        return ResponseEntity.ok(java.util.Map.of("status", "RUNNING", "requeuedFailed", retried.size()));
    }

    private void publishJob(UUID jobId) {
        redisForBatch.opsForStream().add(
                org.springframework.data.redis.connection.stream.StreamRecords.newRecord()
                        .in(dev.sjw.common.queue.QueueKeys.STREAM)
                        .ofMap(java.util.Map.of(dev.sjw.common.queue.QueueKeys.FIELD_JOB_ID,
                                jobId.toString())));
    }

    private BatchView view(BatchRow b) {
        return new BatchView(b.id(), b.status(), b.totalCount(), b.doneCount(),
                b.failedCount(), b.cursorCheckpoint(), b.budgetLimitCalls());
    }

    /** SJW-A19... → 인조 19년 → 1623 + 19 - 1 (eval/measure_e2e.py와 동일 규칙) */
    static Integer reignYearToAd(String docId) {
        try {
            if (docId.charAt(4) == 'A') {
                return 1623 + Integer.parseInt(docId.substring(5, 7)) - 1;
            }
        } catch (RuntimeException ignored) {
        }
        return null;
    }
}
