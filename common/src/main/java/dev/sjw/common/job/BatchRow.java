package dev.sjw.common.job;

import java.util.UUID;

/** batch_job 행 (§8.2). 무료 모드 예산 단위 = LLM 호출 수 (ADR-016). */
public record BatchRow(
        UUID id,
        String rangeSpec,
        int budgetLimitCalls,
        int cursorCheckpoint,
        int totalCount,
        int doneCount,
        int failedCount,
        String status,  // RUNNING | PAUSED | COMPLETED | BUDGET_EXHAUSTED | QUOTA_PAUSED
        String tenantId // 소유 테넌트 — 조회·일시정지·재개의 소유권 검사 기준
) {}
