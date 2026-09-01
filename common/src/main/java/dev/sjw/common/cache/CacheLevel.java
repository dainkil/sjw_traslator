package dev.sjw.common.cache;

/** 캐시 히트 층위 (§5.2) — translation_job.cache_hit_level 값이자 API cacheHit 표기. */
public enum CacheLevel {
    L1_EXACT("L1"),
    L2_TEMPLATE("L2");

    private final String metricLabel;

    CacheLevel(String metricLabel) {
        this.metricLabel = metricLabel;
    }

    /** §9.1 translation.cache.hit 카운터의 level 라벨 (L1/L2). */
    public String metricLabel() {
        return metricLabel;
    }
}
