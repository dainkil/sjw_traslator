package dev.sjw.common.cache;

import dev.sjw.common.util.TextHash;

/**
 * §8.3 캐시 키 계약 (ADR-009). kb_version·prompt_version이 키에 들어가므로
 * KB 데이터 파일이나 프롬프트가 바뀌면(체크섬 파생 버전, M2.5) 키가 저절로 달라진다 —
 * 무효화 코드 0줄. 옛 버전의 고아 엔트리는 TTL이 회수한다.
 */
public final class CacheKeys {

    private CacheKeys() {}

    public static String l1(String kbVersion, String promptVersion, String sourceText) {
        return "cache:l1:" + kbVersion + ":" + promptVersion + ":"
                + TextHash.normalizedHash(sourceText);
    }

    public static String l2(String kbVersion, String promptVersion, String templateHash) {
        return "cache:l2:" + kbVersion + ":" + promptVersion + ":" + templateHash;
    }
}
