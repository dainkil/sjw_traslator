package dev.sjw.common.job;

import java.time.OffsetDateTime;
import java.util.UUID;

/** translation_job 행 (§8.2). */
public record JobRow(
        UUID id,
        String idempotencyKey,
        String sourceText,
        Integer docYear,
        String normalizedHash,
        JobStatus status,
        String modelUsed,
        Integer tokensIn,
        Integer tokensOut,
        UUID batchId,
        String errorClass,
        OffsetDateTime createdAt,
        OffsetDateTime completedAt
) {}
