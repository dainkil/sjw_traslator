package dev.sjw.common.cache;

import dev.sjw.common.util.TextHash;

/**
 * §8.3 캐시 키 계약 (ADR-009). 파이프라인 버전이 키에 들어가므로 KB 데이터·프롬프트·NER 모델이
 * 바뀌면(전부 체크섬 파생 버전) 키가 저절로 달라진다 — 무효화 코드 0줄.
 * 옛 버전의 고아 엔트리는 TTL이 회수한다.
 */
public final class CacheKeys {

    private CacheKeys() {}

    public static String l1(PipelineVersion version, String sourceText) {
        return "cache:l1:" + version.keySegment() + ":" + TextHash.normalizedHash(sourceText);
    }

    public static String l2(PipelineVersion version, String templateHash) {
        return "cache:l2:" + version.keySegment() + ":" + templateHash;
    }
}
