package dev.sjw.common.routing;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import dev.sjw.common.translate.TranslationDtos.EntityDto;
import java.util.List;
import org.junit.jupiter.api.Test;

/** 난이도 판정 규칙 (§5.1을 M4-S1 실측으로 고친 것, ADR-010). */
class TierRouterTest {

    private final TierRouter router = new TierRouter();

    private static EntityDto per(String surface, String kbId, String name, String stage) {
        return new EntityDto(surface, "PER", kbId, name, 0.9, stage, "AMBIGUOUS".equals(stage));
    }

    private static EntityDto other(String surface, String type) {
        return new EntityDto(surface, type, null, null, 0.9, null, false);
    }

    @Test
    void 동명이인_모호가_있으면_T2다() {
        // 후보가 이미 프롬프트에 주입돼 있고 고르는 일이 추론이다 — 상위 모델이 나아질 여지가 있다
        var d = router.classify("傳于李某曰知道",
                List.of(per("李某", null, null, "AMBIGUOUS")));

        assertEquals(Tier.T2, d.tier());
        assertEquals(1, d.signals().ambiguous());
        assertTrue(d.reason().contains("모호"));
    }

    @Test
    void KB_미등재는_T2가_아니다() {
        // 계획서 원안은 MISS도 T2였다. 그러면 29.86%가 상위 모델로 가 quota를 8배 초과하고,
        // 무엇보다 모델을 올려도 역색인에 없는 인물에 대해 아는 바가 늘지 않는다.
        var d = router.classify("傳于某人曰知道",
                List.of(per("某人", null, null, "MISS")));

        assertEquals(Tier.T1, d.tier());
        assertEquals(1, d.signals().kbMiss());
        assertTrue(d.reason().contains("KB 미등재"), "왜 T1인지가 읽혀야 한다: " + d.reason());
    }

    @Test
    void 엔티티_0개에_정형문_패턴이면_T0다() {
        var d = router.classify("傳曰, 知道。", List.of());   // 傳曰 = positive-patterns.tsv 등재 패턴

        assertEquals(Tier.T0, d.tier());
        assertTrue(d.signals().formulaic());
        assertEquals(0, d.signals().entities());
    }

    @Test
    void 엔티티_0개라도_패턴이_없으면_T0이_아니다() {
        // NER 단독으로 T0을 판정하면 안 된다 — 인물이 있는 문장에도 전 토큰 O 예측이 나온다
        // (M1 실측, 계획서 §10 M4). 패턴 결합이 그 방어다.
        var d = router.classify("○ 上在昌德宮。", List.of());

        assertEquals(Tier.T1, d.tier());
        assertFalse(d.signals().formulaic());
    }

    @Test
    void 계획서_표가_정하지_않았던_구간도_전부_판정된다() {
        // 실측에서 35.87%가 미정의였다 — 기본을 T1로 두어 판정되지 않는 문장을 없앤다
        var perOnlyLoc = router.classify("○ 上在昌德宮。", List.of(other("昌德宮", "LOC")));
        var manyConfirmed = router.classify("以李馨長·金瑬·沈悅爲承旨", List.of(
                per("李馨長", "P1", "이형장", "SINGLE"),
                per("金瑬", "P2", "김류", "SINGLE"),
                per("沈悅", "P3", "심열", "SINGLE")));

        assertEquals(Tier.T1, perOnlyLoc.tier());
        assertEquals(1, perOnlyLoc.signals().loc());
        assertEquals(Tier.T1, manyConfirmed.tier());
        assertEquals(3, manyConfirmed.signals().confirmed());
    }

    @Test
    void 모호가_미등재와_함께_있으면_모호가_이긴다() {
        // 모호는 상위 모델이 도울 수 있는 부분이 실재한다 — 같은 문장의 MISS가 그걸 막지 않는다
        var d = router.classify("傳于李某·某人曰知道", List.of(
                per("李某", null, null, "AMBIGUOUS"),
                per("某人", null, null, "MISS")));

        assertEquals(Tier.T2, d.tier());
    }

    @Test
    void 신호는_타입별로_집계된다() {
        var s = router.extract("○ 傳于李馨長曰, 昌德宮。", List.of(
                per("李馨長", "P1", "이형장", "SINGLE"),
                other("昌德宮", "LOC"),
                other("初一日", "DAT")));

        assertEquals(3, s.entities());
        assertEquals(1, s.per());
        assertEquals(1, s.loc());
        assertEquals(1, s.dat());
        assertEquals(1, s.confirmed());
        assertEquals(0, s.kbMiss());
        assertTrue(s.formulaic());
    }
}
