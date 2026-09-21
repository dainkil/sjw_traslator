package dev.sjw.common.llm;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;

class ModelRegistryTest {

    private static ModelSpec spec(String id, String in, String out) {
        return spec(id, in, out, null);
    }

    /** rpm은 실측값만 들어간다 — 미실측이면 null (원칙 4). */
    private static ModelSpec spec(String id, String in, String out, Integer rpm) {
        return new ModelSpec(id, "google-genai", "T0", null, rpm,
                new BigDecimal(in), new BigDecimal(out));
    }

    private final LlmProperties props = new LlmProperties(
            "flash-lite", new BigDecimal("1400"),
            List.of(spec("flash", "0.30", "2.50"), spec("flash-lite", "0.10", "0.40"),
                    spec("gemma", "0", "0")));

    @Test
    void 실측_rpm은_있는_모델만_돌려준다() {
        var withRpm = new LlmProperties("a", new BigDecimal("1400"),
                List.of(spec("a", "0.1", "0.4", 15), spec("b", "0.1", "0.4")));
        ModelRegistry reg = new ModelRegistry(withRpm);

        assertEquals(15, reg.measuredRpm("a").orElseThrow());
        // 미실측 모델과 미등록 모델은 구별 없이 empty — 호출자는 둘 다 전역 기본값으로 탐색한다
        assertEquals(java.util.Optional.empty(), reg.measuredRpm("b"));
        assertEquals(java.util.Optional.empty(), reg.measuredRpm("등록되지-않은-모델"));
    }

    @Test
    void rpm이_0이하면_기동을_막는다() {
        assertThrows(IllegalArgumentException.class,
                () -> spec("a", "0.1", "0.4", 0));
    }

    @Test
    void activeModelResolvesFromRegistry() {
        assertEquals("flash-lite", new ModelRegistry(props).active().id());
    }

    @Test
    void unknownActiveModelFailsStartup() {
        var bad = new LlmProperties("nope", null, props.models());
        assertThrows(IllegalStateException.class, () -> new ModelRegistry(bad));
    }

    @Test
    void unknownModelInCostFails() {
        var reg = new ModelRegistry(props);
        assertThrows(IllegalStateException.class, () -> reg.cost("nope", 1, 1));
    }

    @Test
    void costUsesPerModelCounterfactualPrice() {
        var reg = new ModelRegistry(props);
        // E2E 실측 평균과 같은 자릿수: 820 in / 115 out
        ModelRegistry.Cost flash = reg.cost("flash", 820, 115);
        // (820*0.30 + 115*2.50)/1e6 USD * 1400 KRW = 0.7469
        assertEquals(new BigDecimal("0.7469"), flash.krw());
        assertEquals(new BigDecimal("0.30"), flash.unitPriceIn());

        ModelRegistry.Cost gemma = reg.cost("gemma", 820, 115);
        assertEquals(0, gemma.krw().compareTo(BigDecimal.ZERO));
    }

    @Test
    void nullTokensCountAsZeroButRowStillPossible() {
        var reg = new ModelRegistry(props);
        assertEquals(0, reg.cost("flash", null, null).krw().compareTo(BigDecimal.ZERO));
    }

    @Test
    void duplicateModelIdRejected() {
        var dup = new LlmProperties("flash", null,
                List.of(spec("flash", "1", "1"), spec("flash", "2", "2")));
        assertThrows(IllegalStateException.class, () -> new ModelRegistry(dup));
    }
}
