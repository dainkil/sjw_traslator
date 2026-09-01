package dev.sjw.worker.failure;

/**
 * 실패 분류 (§6). 각 분류는 서로 다른 처리 경로를 갖는다.
 * 분류 근거 문자열은 2026-08-31 실측 로그 그대로다 (docs/troubleshooting.md).
 */
public enum ErrorClass {

    /** 429 + "spending cap": 프로젝트 지출 상한. 재시도 무의미(영구) — 배치 정지 + DLQ */
    SPEND_CAP(false, true),
    /** 429 + "PerDay": 일일 무료 quota 소진. 오늘은 영구, 내일 리셋 — 배치 QUOTA_PAUSED, job은 FAILED 유지 */
    QUOTA_DAILY(false, false),
    /** 429 (분당): 순간 rate limit — 즉시 재시도(backoff)로 흡수 가능 */
    RATE_LIMITED(true, false),
    /** 5xx / 503 overloaded: 일시 장애 — 재시도 */
    SERVER_ERROR(true, false),
    /** 네트워크/응답 타임아웃 — 재시도 */
    TIMEOUT(true, false),
    /** 404 등 모델 자체 불가(단종·미제공): 영구 — DLQ */
    MODEL_UNAVAILABLE(false, true),
    /** 구조화 출력 파싱 실패: 호출은 발생(과금 기록 필수). 비결정성이라 1회 재시도 가치 있음 */
    PARSE_ERROR(true, false),
    /** 콘텐츠 필터: 영구 — DLQ */
    CONTENT_FILTERED(false, true),
    /** NER 인식기 동작 불능 (M2.5): 내부 인프라 장애 — 재시도. LLM 서킷 통계에서 제외해야 한다 */
    NER_UNAVAILABLE(true, false),
    /** 미분류: 재전달 상한까지 재시도 후 DLQ */
    UNKNOWN(true, false);

    private final boolean transientRetry; // 재시도(즉시 또는 재전달)로 회복 가능한가
    private final boolean deadImmediately; // 즉시 DLQ 대상인가

    ErrorClass(boolean transientRetry, boolean deadImmediately) {
        this.transientRetry = transientRetry;
        this.deadImmediately = deadImmediately;
    }

    public boolean transientRetry() {
        return transientRetry;
    }

    public boolean deadImmediately() {
        return deadImmediately;
    }
}
