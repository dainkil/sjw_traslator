package dev.sjw.common.queue;

/** §8.3 Redis 키 설계 — api(발행)와 worker(소비)가 공유하는 유일한 계약. */
public final class QueueKeys {

    private QueueKeys() {}

    public static final String STREAM = "stream:translation";
    public static final String DLQ = "stream:translation:dlq";
    public static final String CONSUMER_GROUP = "workers";

    /** 메시지 필드: 본문은 Postgres에 있고 스트림에는 jobId만 싣는다 (재전달 안전). */
    public static final String FIELD_JOB_ID = "jobId";
}
