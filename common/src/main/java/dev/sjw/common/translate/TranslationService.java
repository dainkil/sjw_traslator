package dev.sjw.common.translate;

import dev.sjw.common.kb.KnowledgeSource;
import dev.sjw.common.kb.LinkResult;
import dev.sjw.common.llm.Translator;
import dev.sjw.common.ner.EntityRecognizer;
import dev.sjw.common.ner.NerEntity;
import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.translate.TranslationDtos.LlmOutput;
import dev.sjw.common.translate.TranslationDtos.Meta;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationDtos.UncertainSpan;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

@Service
public class TranslationService {

    private final EntityRecognizer nerClient;
    private final KnowledgeSource kb;
    private final PromptAssembler promptAssembler;
    private final Translator translator;

    public TranslationService(EntityRecognizer nerClient, KnowledgeSource kb,
                              PromptAssembler promptAssembler, Translator translator) {
        this.nerClient = nerClient;
        this.kb = kb;
        this.promptAssembler = promptAssembler;
        this.translator = translator;
    }

    /** 현재 호출 대상 모델 id — rate 버킷 키와 원장 기록의 기준 (M4에서 티어 라우팅이 이 자리를 대체한다). */
    public String model() {
        return translator.modelId();
    }

    /** 파이프라인 전처리 결과 (①NER ②링킹 ③프롬프트) — 동기·스트림 경로가 공유한다. */
    public record Prepared(String prompt, List<EntityDto> entities,
                           List<UncertainSpan> kbMisses, Map<String, Long> latencyMs) {}

    public Prepared prepare(String text, Integer year) {
        Map<String, Long> lat = new LinkedHashMap<>();
        int currentYear = year == null ? Integer.MAX_VALUE : year;

        // ① NER
        long t = System.nanoTime();
        List<NerEntity> nerEntities = nerClient.extract(text);
        lat.put("ner", ms(t));

        // ② KB 링킹 (PER만)
        t = System.nanoTime();
        List<EntityDto> entityDtos = new ArrayList<>();
        List<PromptAssembler.LinkedEntity> linked = new ArrayList<>();
        List<UncertainSpan> kbMisses = new ArrayList<>();
        for (NerEntity e : nerEntities) {
            if (!"PER".equals(e.type())) {
                entityDtos.add(new EntityDto(e.surface(), e.type(), null, null,
                        e.score(), null, false));
                continue;
            }
            LinkResult r = kb.link(e.surface(), currentYear, text);
            String kbId = r.resolvedId();
            String resolvedName = kbId != null ? kb.person(kbId).hangulName() : null;
            entityDtos.add(new EntityDto(e.surface(), e.type(), kbId, resolvedName,
                    e.score(), r.stage().name(), r.stage() == LinkResult.Stage.AMBIGUOUS));
            if (kbId != null) {
                linked.add(new PromptAssembler.LinkedEntity(
                        e.surface(), List.of(kb.person(kbId)), true));
            } else if (r.stage() == LinkResult.Stage.AMBIGUOUS && !r.candidateIds().isEmpty()) {
                // 모호 후보(≤3)를 프롬프트에 모두 주입 — 판단은 LLM에 위임 (§7)
                linked.add(new PromptAssembler.LinkedEntity(
                        e.surface(), r.candidateIds().stream().map(kb::person).toList(), false));
            } else if (r.stage() == LinkResult.Stage.MISS) {
                kbMisses.add(new UncertainSpan(e.surface(), "KB_MISS"));
            }
        }
        lat.put("link", ms(t));

        // ③ 프롬프트 조립
        t = System.nanoTime();
        String prompt = promptAssembler.assemble(text, linked);
        lat.put("prompt", ms(t));
        return new Prepared(prompt, entityDtos, kbMisses, lat);
    }

    /**
     * 단건 SSE용 토큰 스트리밍 (D7). Structured Output 없이 번역문만 흘린다 —
     * 스키마 보장이 필요한 소비자는 동기/비동기 경로를 쓴다.
     */
    public reactor.core.publisher.Flux<String> translateStream(Prepared prep) {
        return translator.stream(prep.prompt() + "\n번역문만 출력하세요. 다른 텍스트를 붙이지 마세요.");
    }

    public TranslationResponse translate(String text, Integer year) {
        return translate(prepare(text, year));
    }

    /**
     * 전처리 완료분으로 LLM 호출만 수행. 워커는 이 오버로드를 쓴다 —
     * prepare(무료·수십 ms)를 rate permit 밖에서 끝내야 NER 장애가 버킷 토큰을 태우지 않고,
     * 재시도가 LLM 호출만 반복한다.
     */
    public TranslationResponse translate(Prepared prep) {
        Map<String, Long> lat = new LinkedHashMap<>(prep.latencyMs());
        List<EntityDto> entityDtos = prep.entities();
        List<UncertainSpan> kbMisses = prep.kbMisses();
        String prompt = prep.prompt();

        // ④ LLM 호출 (Structured Output — 변환을 수동으로 하여 파싱 실패 시에도 usage를 보존)
        long t = System.nanoTime();
        var converter = new org.springframework.ai.converter.BeanOutputConverter<>(LlmOutput.class);
        Translator.LlmReply reply = translator.call(prompt + "\n" + converter.getFormat());
        lat.put("llm", ms(t));

        LlmOutput out;
        try {
            out = converter.convert(reply.text() == null ? "" : reply.text());
        } catch (RuntimeException parseError) {
            throw new LlmParseException(translator.modelId(),
                    reply.tokensIn(), reply.tokensOut(), parseError);
        }
        lat.put("total", lat.values().stream().mapToLong(Long::longValue).sum());

        List<UncertainSpan> uncertain = new ArrayList<>(kbMisses);
        if (out != null && out.uncertainSpans() != null) {
            uncertain.addAll(out.uncertainSpans());
        }
        return new TranslationResponse(
                out == null ? null : out.translatedText(),
                entityDtos,
                uncertain,
                new Meta(translator.modelId(), kb.version(),
                        reply.tokensIn(), reply.tokensOut(), lat)
        );
    }

    private static long ms(long fromNanos) {
        return (System.nanoTime() - fromNanos) / 1_000_000;
    }
}
