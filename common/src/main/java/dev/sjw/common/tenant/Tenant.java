package dev.sjw.common.tenant;

/**
 * 테넌트 — rate·예산·원장 격리의 단위 (D10). LLM 키는 이 객체에도, 어디에도 담지 않는다.
 *
 * @param operatorAccess 운영자 키(GEMINI_API_KEY)로 도는 경로(비동기 job·배치)를 쓸 수 있는가.
 *                       공개 배포에서 발급 키의 기본값은 false — 운영자 무료 quota를 지키는 문이다 (V5)
 */
public record Tenant(String id, String displayName, int dailyCallLimit, boolean operatorAccess) {

    public static final String DEFAULT_ID = "default";
}
