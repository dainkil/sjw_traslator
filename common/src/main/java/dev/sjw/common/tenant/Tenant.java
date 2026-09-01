package dev.sjw.common.tenant;

/** 테넌트 — rate·예산·원장 격리의 단위 (D10). LLM 키는 이 객체에도, 어디에도 담지 않는다. */
public record Tenant(String id, String displayName, int dailyCallLimit) {

    public static final String DEFAULT_ID = "default";
}
