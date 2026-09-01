package dev.sjw.common.quality;

/** 런타임 품질 등급 (§5.4). LLM 추가 호출 0회의 결정론 판정. */
public enum QualityGrade {
    /** 링크 확정 엔티티 전건이 번역문에 반영 + 스키마 통과 */
    VERIFIED,
    /** KB_MISS 존재 (M3부터: L2 캐시 재주입 결과 포함) — 표본 재검증 대상 */
    DEGRADED,
    /** 확정 엔티티 누락 또는 번역문 부재 — 상위 티어 재호출 대상, 재실패 시 검수 큐 */
    REJECTED
}
