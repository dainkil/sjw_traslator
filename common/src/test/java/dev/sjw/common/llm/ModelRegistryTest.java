package dev.sjw.common.llm;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;

class ModelRegistryTest {

    private static ModelSpec spec(String id, String in, String out) {
        return new ModelSpec(id, "google-genai", "T0", null,
                new BigDecimal(in), new BigDecimal(out));
    }

    private final LlmProperties props = new LlmProperties(
            "flash-lite", new BigDecimal("1400"),
            List.of(spec("flash", "0.30", "2.50"), spec("flash-lite", "0.10", "0.40"),
                    spec("gemma", "0", "0")));

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
