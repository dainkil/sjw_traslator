package dev.sjw.common.llm;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;

/** provider 축 분기 — 어느 어댑터인지는 코드가 아니라 레지스트리의 provider가 정한다 (ADR-018). */
class TranslatorFactoryTest {

    private static ModelSpec spec(String id, String provider) {
        return new ModelSpec(id, provider, "T0", null, null, BigDecimal.ZERO, BigDecimal.ZERO);
    }

    private static TranslatorFactory factory() {
        var registry = new ModelRegistry(new LlmProperties("fake-flash-lite", null,
                List.of(spec("fake-flash-lite", "fake"), spec("gemini-x", "google-genai"))));
        // ChatClient.Builder는 fake 경로에서 쓰이지 않는다 — null이어도 fake는 만들어져야 한다
        return new TranslatorFactory(null, registry, new FakeProvider(FakeLlmProperties.defaults()));
    }

    @Test
    void fake_provider_모델은_FakeTranslator를_만든다() {
        var t = factory().forModel("fake-flash-lite");
        assertInstanceOf(FakeTranslator.class, t);
        assertEquals("fake-flash-lite", t.modelId());
        assertInstanceOf(FakeTranslator.class, factory().forModelWithKey("fake-flash-lite", "any-key"));
    }

    @Test
    void isFake는_레지스트리의_provider를_본다() {
        var f = factory();
        assertTrue(f.isFake("fake-flash-lite"));
        assertFalse(f.isFake("gemini-x"));
        assertFalse(f.isFake("unregistered"));
        assertFalse(f.isFake(null));
    }

    @Test
    void 레지스트리에_없는_모델은_거부() {
        assertThrows(IllegalStateException.class, () -> factory().forModel("nope"));
    }

    @Test
    void 모르는_provider는_기동_시점에_실패() {
        assertThrows(IllegalArgumentException.class, () -> spec("m", "openai"));
        spec("m", null);   // 미기입 = google-genai
    }
}
