package dev.sjw.common.llm;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.common.kb.FileKnowledgeSource;
import dev.sjw.common.ner.RulePatternRecognizer;
import dev.sjw.common.quality.QualityGate;
import dev.sjw.common.quality.QualityGrade;
import dev.sjw.common.translate.PromptAssembler;
import dev.sjw.common.translate.TranslationDtos.LlmOutput;
import dev.sjw.common.translate.TranslationService;
import java.time.Clock;
import org.junit.jupiter.api.Test;
import org.springframework.ai.converter.BeanOutputConverter;

/**
 * 가짜 Translator가 지키는 계약 — 프롬프트 파싱은 실제 PromptAssembler 출력으로, 파이프라인 결합은
 * 실제 TranslationService(규칙 NER + 인조 KB) + QualityGate로 검증한다. 네트워크 0, quota 0.
 */
class FakeTranslatorTest {

    private static final String SOURCE = "以兪榥爲承旨";
    private static final ObjectMapper JSON = new ObjectMapper();

    private static FakeProvider provider(double dropNameRate) {
        return new FakeProvider(new FakeLlmProperties(0, 0, null, null, 0.0, dropNameRate, null), Clock.systemUTC());
    }

    private static TranslationService service(FakeProvider p) throws java.io.IOException {
        return new TranslationService(new RulePatternRecognizer(), new FileKnowledgeSource("../kb", "injo"),
                new PromptAssembler(), p.translator("fake-flash-lite"));
    }

    @Test
    void 실제_조립_프롬프트에서_KB_블록을_읽어_표면형을_한글명으로_치환한다() throws Exception {
        var prep = service(provider(0)).prepare(SOURCE, 1636);
        assertTrue(prep.prompt().contains("[등장 인물 한자→한글]"), "전제: 兪榥이 KB로 확정돼야 한다\n" + prep.prompt());
        String prompt = prep.prompt() + "\n" + new BeanOutputConverter<>(LlmOutput.class).getFormat();   // TranslationService가 붙이는 꼬리

        assertEquals("以유황爲承旨", FakeTranslator.render(prompt, false));
        assertEquals(SOURCE, FakeTranslator.render(prompt, true));   // 첫 확정 인명을 빠뜨리면 한자가 남는다 → 게이트가 잡을 것
    }

    @Test
    void 동명이인_후보는_첫_후보를_쓴다() {
        String prompt = "머리\n\n[등장 인물 한자→한글]\n"
                + "  · 金瑬 → 동명이인 후보 중 문맥으로 판단: 김류(활동 1600~, 영의정) / 김류이(활동 1650~)\n\n"
                + "以金瑬爲承旨";
        assertEquals("以김류爲承旨", FakeTranslator.render(prompt, false));
    }

    @Test
    void call은_Structured_Output_JSON과_usage를_돌려준다() throws Exception {
        var t = provider(0).translator("fake-flash-lite");
        var reply = t.call("본문\n\n[등장 인물 한자→한글]\n  · 兪榥 → 유황  (관직: 승지)\n\n" + SOURCE);
        var out = JSON.readValue(reply.text(), LlmOutput.class);
        assertEquals("以유황爲承旨", out.translatedText());
        assertNotNull(out.uncertainSpans());
        assertTrue(reply.tokensIn() > 0 && reply.tokensOut() > 0);
        assertEquals("fake-flash-lite", t.modelId());
    }

    @Test
    void stream은_같은_본문을_청크로_흘린다() {
        var t = provider(0).translator("fake-flash-lite");
        String joined = String.join("", t.stream("x\n\n[등장 인물 한자→한글]\n  · 兪榥 → 유황\n\n" + SOURCE)
                .collectList().block());
        assertEquals("以유황爲承旨", joined);
    }

    @Test
    void 파이프라인_끝까지_통과하면_게이트_VERIFIED_이름을_빠뜨리면_REJECTED() throws Exception {
        var gate = new QualityGate();

        var ok = service(provider(0)).translate(SOURCE, 1636);
        assertEquals("以유황爲承旨", ok.translatedText());
        assertEquals("fake-flash-lite", ok.meta().model());
        assertEquals(QualityGrade.VERIFIED, gate.grade(ok).grade());

        var dropped = service(provider(1.0)).translate(SOURCE, 1636);
        assertEquals(QualityGrade.REJECTED, gate.grade(dropped).grade());
    }
}
