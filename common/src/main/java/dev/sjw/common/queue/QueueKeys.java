package dev.sjw.common.queue;

/** §8.3 Redis 키 설계 — api(발행)와 worker(소비)가 공유하는 유일한 계약. */
public final class QueueKeys {

    private QueueKeys() {}

    public static final String STREAM = "stream:translation";
    public static final String DLQ = "stream:translation:dlq";
    public static final String CONSUMER_GROUP = "workers";

    /** 메시지 필드: 본문은 Postgres에 있고 스트림에는 jobId만 싣는다 (재전달 안전). */
    public static final String FIELD_JOB_ID = "jobId";

    /**
     * 적응형 rate control의 토큰 버킷. scope = "{tenant}:{model}" ({@link #rateScope}) —
     * provider 무료 quota가 모델별로 독립이고(실측, ADR-016), BYOK에서는 키가 테넌트별이라
     * quota 풀 자체가 테넌트×모델 단위다 (D10, ADR-020).
     */
    public static String rateBucket(String scope) {
        return "rate:bucket:" + scope;
    }

    /** 버킷 스코프: 테넌트×모델. */
    public static String rateScope(String tenantId, String model) {
        return tenantId + ":" + model;
    }

    /** 테넌트 일일 소진량 카운터 (§8.3). 무료 티어에서는 호출 수가 예산이다. */
    public static String budgetDaily(String tenantId, String yyyyMmDd) {
        return "budget:daily:" + tenantId + ":" + yyyyMmDd;
    }

    /**
     * provider 일일 quota 예약 카운터 (M4-S1, ADR-010). <b>테넌트가 들어가지 않는다</b> —
     * 무료 quota는 프로젝트×모델 단위라(429 응답의 {@code quotaId}가
     * {@code ...PerProjectPerModel-FreeTier}) 테넌트별로 쪼개면 합계가 한도를 넘는다.
     * {@link #budgetDaily}와 다른 축이다: 그쪽은 "테넌트가 쓸 수 있는 양", 이쪽은
     * "provider가 허용하는 양".
     */
    public static String providerQuotaDaily(String model, String yyyyMmDd) {
        return "quota:daily:" + model + ":" + yyyyMmDd;
    }
}
