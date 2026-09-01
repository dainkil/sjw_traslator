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
}
