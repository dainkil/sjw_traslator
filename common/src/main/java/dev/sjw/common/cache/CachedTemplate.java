package dev.sjw.common.cache;

/**
 * L2 캐시에 들어가는 값 (Redis JSON) — <b>번역문 템플릿</b>이다 (§5.2, ADR-009).
 *
 * <p>L1 값과 달리 엔티티를 담지 않는다. L2 히트는 "구조는 같고 인물이 다른" 문장에 쓰이므로
 * 엔티티는 캐시가 아니라 <b>지금 이 문장의 NER·링킹 결과</b>여야 한다 — 캐시된 엔티티를 되살리면
 * 다른 사람의 이름을 서빙하게 된다. 그래서 L2는 NER 추론을 건너뛰지 못한다(L1과의 차이).
 *
 * <p>{@code slotCount}는 진단용이다. 구조 불일치는 재주입이 어차피 취소시키지만(마커 누락·잔존),
 * 로그에서 "몇 자리짜리 틀에 몇 자리를 꽂으려 했는가"가 보이면 원인 파악이 빠르다.
 */
public record CachedTemplate(
        String translationTemplate,
        String producedModel,
        int slotCount,
        String storedAt) {}
