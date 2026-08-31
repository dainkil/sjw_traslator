package dev.sjw.common.job;

public enum JobStatus {
    PENDING,    // 큐에 발행됨
    RUNNING,    // 워커가 집었음
    SUCCEEDED,  // 결과 저장 완료 — 재전달돼도 다시 처리하지 않는다 (멱등 기준점)
    FAILED,     // 재시도 가능 실패 (S4에서 분류 세분화)
    DEAD        // DLQ 이관 — 재시도 불가
}
