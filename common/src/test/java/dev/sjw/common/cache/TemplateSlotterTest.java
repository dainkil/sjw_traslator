package dev.sjw.common.cache;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import dev.sjw.common.cache.TemplateSlotter.SlottedSource;
import dev.sjw.common.translate.TranslationDtos.EntityDto;
import java.util.List;
import org.junit.jupiter.api.Test;

class TemplateSlotterTest {

    private final TemplateSlotter slotter = new TemplateSlotter();

    private static EntityDto per(String surface, String kbId, String name) {
        return new EntityDto(surface, "PER", kbId, name, 0.99, "SINGLE", false);
    }

    private static EntityDto missPer(String surface) {
        return new EntityDto(surface, "PER", null, null, 0.99, "MISS", false);
    }

    private static EntityDto pos(String surface) {
        return new EntityDto(surface, "POS", null, null, 0.99, null, false);
    }

    @Test
    void 확정_PER만_슬롯화되고_POS와_미확정은_문면_그대로_남는다() {
        var src = slotter.slotSource("命金瑬爲都巡檢使",
                List.of(per("金瑬", "M1", "김류"), pos("都巡檢使"))).orElseThrow();
        assertEquals("命⟪PER1⟫爲都巡檢使", src.template());
        assertEquals(1, src.slots().size());
        assertEquals("김류", src.slots().get(0).resolvedName());

        assertTrue(slotter.slotSource("尹昉入侍", List.of(missPer("尹昉"))).isEmpty());
    }

    @Test
    void 구조가_같으면_인명이_달라도_template_hash가_같다() {
        var a = slotter.slotSource("命金瑬爲大將", List.of(per("金瑬", "M1", "김류"))).orElseThrow();
        var b = slotter.slotSource("命李貴爲大將", List.of(per("李貴", "M2", "이귀"))).orElseThrow();
        var c = slotter.slotSource("以李貴爲大將", List.of(per("李貴", "M2", "이귀"))).orElseThrow();
        assertEquals(slotter.templateHash(a), slotter.templateHash(b));
        assertNotEquals(slotter.templateHash(a), slotter.templateHash(c));
    }

    @Test
    void 슬롯_번호는_원문_등장_위치_순이고_긴_표면형부터_치환한다() {
        var src = slotter.slotSource("金自點與自點論事",
                List.of(per("自點", "M1", "김자점"), per("金自點", "M1", "김자점"))).orElseThrow();
        assertEquals("⟪PER1⟫與⟪PER2⟫論事", src.template());
        assertEquals("金自點", src.slots().get(0).surface());
        assertEquals("自點", src.slots().get(1).surface());
    }

    @Test
    void 번역문_템플릿화는_전체_이름이_있을_때만_성립한다() {
        var src = slotter.slotSource("命金瑬爲大將", List.of(per("金瑬", "M1", "김류"))).orElseThrow();
        assertEquals("⟪PER1⟫를 대장으로 삼았다.",
                slotter.templateizeTranslation("김류를 대장으로 삼았다.", src).orElseThrow());

        // 게이트는 이름부("문회")도 반영으로 인정하지만 템플릿화는 전체형만 — 보수적 적재
        var jeong = slotter.slotSource("鄭文翼啓曰", List.of(per("鄭文翼", "M2", "정문익"))).orElseThrow();
        assertTrue(slotter.templateizeTranslation("문익이 아뢰기를", jeong).isEmpty());
    }

    @Test
    void 재주입은_받침에_맞게_조사를_보정한다() {
        var withBatchim = slotter.slotSource("金尙憲啓曰",
                List.of(per("金尙憲", "M1", "김상헌"))).orElseThrow();
        var noBatchim = slotter.slotSource("李曙啓曰",
                List.of(per("李曙", "M2", "이서"))).orElseThrow();

        assertEquals("이서가 아뢰기를", slotter.reinject("⟪PER1⟫이 아뢰기를", noBatchim).orElseThrow());
        assertEquals("김상헌을 파직하였다", slotter.reinject("⟪PER1⟫를 파직하였다", withBatchim).orElseThrow());
        assertEquals("이서라 하였다", slotter.reinject("⟪PER1⟫이라 하였다", noBatchim).orElseThrow());
        assertEquals("김상헌이라 하였다", slotter.reinject("⟪PER1⟫이라 하였다", withBatchim).orElseThrow());
        // 같은 마커 다회 출현도 전부 치환·보정된다
        assertEquals("이서가 오니 이서를 맞았다",
                slotter.reinject("⟪PER1⟫이 오니 ⟪PER1⟫을 맞았다", noBatchim).orElseThrow());
    }

    @Test
    void 조사_뒤가_한글이면_다음_단어의_첫_글자일_수_있어_보정하지_않는다() {
        var noBatchim = slotter.slotSource("李曙啓曰",
                List.of(per("李曙", "M2", "이서"))).orElseThrow();
        // "이번에"의 "이"는 조사가 아니다 — 건드리지 않는다
        assertEquals("이서 이번에 올라왔다",
                slotter.reinject("⟪PER1⟫ 이번에 올라왔다", noBatchim).orElseThrow());
        assertEquals("이서가문의 일",
                slotter.reinject("⟪PER1⟫가문의 일", noBatchim).orElseThrow());
    }

    @Test
    void 슬롯_구조_불일치는_empty로_fallback_신호를_준다() {
        var oneSlot = slotter.slotSource("金尙憲啓曰",
                List.of(per("金尙憲", "M1", "김상헌"))).orElseThrow();
        // 템플릿에 마커가 남는다 — 새 문장에 없는 슬롯
        assertTrue(slotter.reinject("⟪PER1⟫와 ⟪PER2⟫를 불렀다", oneSlot).isEmpty());

        SlottedSource twoSlots = slotter.slotSource("金瑬李貴入侍",
                List.of(per("金瑬", "M1", "김류"), per("李貴", "M2", "이귀"))).orElseThrow();
        // 새 문장 슬롯이 템플릿에 없다
        assertTrue(slotter.reinject("⟪PER1⟫만 입시하였다", twoSlots).isEmpty());
    }
}
