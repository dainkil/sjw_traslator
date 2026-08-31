package dev.sjw.api.job;

import dev.sjw.common.job.JobRow;
import dev.sjw.common.job.JobStatus;
import dev.sjw.common.job.TranslationJobRepository;
import dev.sjw.common.queue.QueueKeys;
import dev.sjw.common.translate.TranslationDtos.TranslateRequest;
import dev.sjw.common.util.TextHash;
import jakarta.validation.Valid;
import java.util.Map;
import java.util.UUID;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 비동기 경로 (ADR-001): 수용·검증 후 job 발행 → 202. 처리는 Worker가 한다.
 */
@RestController
@RequestMapping("/api/v1/translations")
public class JobController {

    private final TranslationJobRepository jobs;
    private final StringRedisTemplate redis;

    public JobController(TranslationJobRepository jobs, StringRedisTemplate redis) {
        this.jobs = jobs;
        this.redis = redis;
    }

    public record JobAccepted(UUID jobId, String status) {}

    public record JobView(UUID jobId, String status, String translatedText,
                          String model, Integer tokensIn, Integer tokensOut,
                          String errorClass) {}

    @PostMapping
    public ResponseEntity<JobAccepted> submit(@Valid @RequestBody TranslateRequest req,
                                              @RequestHeader(value = "Idempotency-Key", required = false)
                                              String idempotencyKey) {
        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            var existing = jobs.findByIdempotencyKey(idempotencyKey);
            if (existing.isPresent()) {
                // 같은 키 재제출 = 같은 job. 중복 발행·중복 과금 없음 (§6 멱등 키)
                JobRow j = existing.get();
                return ResponseEntity.status(HttpStatus.ACCEPTED)
                        .body(new JobAccepted(j.id(), j.status().name()));
            }
        }
        UUID id = UUID.randomUUID();
        jobs.insertPending(id, idempotencyKey, req.text(), req.year(),
                TextHash.normalizedHash(req.text()), null);
        publish(id);
        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .body(new JobAccepted(id, JobStatus.PENDING.name()));
    }

    @GetMapping("/{jobId}")
    public ResponseEntity<JobView> get(@PathVariable UUID jobId) {
        return jobs.findById(jobId)
                .map(j -> ResponseEntity.ok(new JobView(
                        j.id(), j.status().name(),
                        j.status() == JobStatus.SUCCEEDED
                                ? jobs.findResultJson(j.id()).orElse(null) : null,
                        j.modelUsed(), j.tokensIn(), j.tokensOut(), j.errorClass())))
                .orElse(ResponseEntity.notFound().build());
    }

    private void publish(UUID jobId) {
        redis.opsForStream().add(StreamRecords.newRecord()
                .in(QueueKeys.STREAM)
                .ofMap(Map.of(QueueKeys.FIELD_JOB_ID, jobId.toString())));
    }
}
