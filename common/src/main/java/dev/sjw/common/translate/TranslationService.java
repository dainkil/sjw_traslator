package dev.sjw.common.translate;

import dev.sjw.common.kb.KnowledgeBase;
import dev.sjw.common.kb.LinkResult;
import dev.sjw.common.ner.NerClient;
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
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class TranslationService {

    private final NerClient nerClient;
    private final KnowledgeBase kb;
    private final PromptAssembler promptAssembler;
    private final ChatClient chatClient;
    private final String model;

    public TranslationService(NerClient nerClient, KnowledgeBase kb,
                              PromptAssembler promptAssembler, ChatClient.Builder builder,
                              @Value("${spring.ai.google.genai.chat.options.model}") String model) {
        this.nerClient = nerClient;
        this.kb = kb;
        this.promptAssembler = promptAssembler;
        this.chatClient = builder.build();
        this.model = model;
    }

    /** 현재 호출 대상 모델 id — rate 버킷 키와 원장 기록의 기준 (M4에서 티어 라우팅이 이 자리를 대체한다). */
    public String model() {
        return model;
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
        return chatClient.prompt()
                .user(prep.prompt() + "\n번역문만 출력하세요. 다른 텍스트를 붙이지 마세요.")
                .stream().content();
    }

    public TranslationResponse translate(String text, Integer year) {
        long start = System.nanoTime();
        Prepared prep = prepare(text, year);
        Map<String, Long> lat = new LinkedHashMap<>(prep.latencyMs());
        List<EntityDto> entityDtos = prep.entities();
        List<UncertainSpan> kbMisses = prep.kbMisses();
        String prompt = prep.prompt();

        // ④ LLM 호출 (Structured Output — 변환을 수동으로 하여 파싱 실패 시에도 usage를 보존)
        long t = System.nanoTime();
        var converter = new org.springframework.ai.converter.BeanOutputConverter<>(LlmOutput.class);
        var chatResponse = chatClient.prompt()
                .user(prompt + "\n" + converter.getFormat())
                .call().chatResponse();
        lat.put("llm", ms(t));

        var usage = chatResponse == null ? null : chatResponse.getMetadata().getUsage();
        String rawText = chatResponse == null ? null
                : chatResponse.getResult().getOutput().getText();
        LlmOutput out;
        try {
            out = converter.convert(rawText == null ? "" : rawText);
        } catch (RuntimeException parseError) {
            throw new LlmParseException(model,
                    usage == null ? null : usage.getPromptTokens(),
                    usage == null ? null : usage.getCompletionTokens(), parseError);
        }
        lat.put("total", (System.nanoTime() - start) / 1_000_000);

        List<UncertainSpan> uncertain = new ArrayList<>(kbMisses);
        if (out != null && out.uncertainSpans() != null) {
            uncertain.addAll(out.uncertainSpans());
        }
        return new TranslationResponse(
                out == null ? null : out.translatedText(),
                entityDtos,
                uncertain,
                new Meta(model, kb.version(),
                        usage == null ? null : usage.getPromptTokens(),
                        usage == null ? null : usage.getCompletionTokens(),
                        lat)
        );
    }

    private static long ms(long fromNanos) {
        return (System.nanoTime() - fromNanos) / 1_000_000;
    }
}
