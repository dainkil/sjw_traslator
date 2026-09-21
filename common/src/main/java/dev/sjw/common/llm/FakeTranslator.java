package dev.sjw.common.llm;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

/**
 * {@link Translator}의 두 번째 provider 구현 — 네트워크 0, quota 소모 0 (ADR-018 재검토 조건의 이행).
 *
 * "번역"은 프롬프트의 [등장 인물 한자→한글] 블록을 읽어 원문의 표면형을 한글명으로 치환한 문자열이다.
 * LLM 흉내가 아니라 <b>파이프라인이 LLM에 기대는 계약만</b> 지킨다:
 * <ul>
 *   <li>Structured Output — {@code {"translatedText", "uncertainSpans"}} JSON (파서 경로 동일)</li>
 *   <li>확정 인명이 번역문에 등장 → 품질 게이트 VERIFIED. {@code dropNameRate}로 REJECTED 유발 가능</li>
 *   <li>등장 순서 보존 → L2 템플릿 슬롯팅이 성립</li>
 *   <li>usage 동반 — 토큰 수는 문자 수 × 0.65 (M1 실측 평균 877 tok / 프롬프트 ≈1,350자에서 역산, 추정)</li>
 * </ul>
 * 프롬프트 파싱은 {@code PromptAssembler}가 Java에서 조립하는 KB 블록 형식에만 의존한다 — 템플릿 변형
 * (eval/prompts/*.st)과 무관하다. 원문은 마지막 빈 줄 뒤의 텍스트로 본다 (모든 템플릿이 {original}로 끝난다).
 */
public final class FakeTranslator implements Translator {

    /** PromptAssembler.assemble()이 만드는 KB 블록 — 헤더 뒤 빈 줄까지, 한 줄이 "  · 表面 → 한글명  (관직: …)" 또는 "… → 동명이인 후보 중 문맥으로 판단: A(…) / B(…)". */
    private static final String KB_HEADER = "[등장 인물 한자→한글]";
    private static final Pattern KB_LINE = Pattern.compile("^\\s*·\\s*(\\S+)\\s*→\\s*(.+?)\\s*$", Pattern.MULTILINE);
    private static final String AMBIGUOUS_MARK = "동명이인 후보 중 문맥으로 판단:";
    /** TranslationService가 프롬프트 뒤에 붙이는 꼬리 — 이 앞까지가 조립된 프롬프트다. */
    private static final String[] TAILS = {"Your response should be in JSON format", "번역문만 출력하세요"};
    private static final double TOKENS_PER_CHAR = 0.65;
    private static final int STREAM_CHUNK_CHARS = 6;

    private static final ObjectMapper JSON = new ObjectMapper();

    private final String modelId;
    private final FakeProvider provider;

    FakeTranslator(String modelId, FakeProvider provider) {
        this.modelId = modelId;
        this.provider = provider;
    }

    @Override
    public String modelId() {
        return modelId;
    }

    @Override
    public LlmReply call(String prompt) {
        provider.admit(modelId);
        String text = render(prompt, provider.dropName());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("translatedText", text);
        out.put("uncertainSpans", List.of());
        try {
            String json = JSON.writeValueAsString(out);
            return new LlmReply(json, tokens(prompt), tokens(json));
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public Flux<String> stream(String prompt) {
        return Flux.defer(() -> {
            provider.admitStream(modelId);
            String text = render(prompt, provider.dropName());
            List<String> chunks = new ArrayList<>();
            for (int i = 0; i < text.length(); i += STREAM_CHUNK_CHARS) {
                chunks.add(text.substring(i, Math.min(text.length(), i + STREAM_CHUNK_CHARS)));
            }
            // 첫 토큰까지 latency, 그 뒤 청크 간격은 그 1/10 — 실 SSE의 "기다렸다가 흘러나오는" 모양
            long firstToken = provider.latencyMs();
            Duration perChunk = Duration.ofMillis(Math.max(1, firstToken / 10));
            return Mono.delay(Duration.ofMillis(firstToken))
                    .thenMany(Flux.fromIterable(chunks).delayElements(perChunk));
        });
    }

    /** 원문의 표면형을 한글명으로 치환. dropFirst면 첫 확정 인명을 건너뛴다 (한자 그대로 남아 게이트가 잡는다). */
    static String render(String prompt, boolean dropFirst) {
        String body = prompt;
        for (String tail : TAILS) {
            int at = body.indexOf(tail);
            if (at >= 0) {
                body = body.substring(0, at);
            }
        }
        body = body.strip();
        int lastBlank = body.lastIndexOf("\n\n");
        String original = (lastBlank >= 0 ? body.substring(lastBlank + 2) : body).strip();

        String out = original;
        boolean dropped = !dropFirst;
        Matcher m = KB_LINE.matcher(body);
        while (m.find()) {
            String surface = m.group(1);
            String rhs = m.group(2);
            String name = rhs.startsWith(AMBIGUOUS_MARK)
                    ? firstCandidate(rhs.substring(AMBIGUOUS_MARK.length()))
                    : rhs.replaceFirst("\\s*\\(관직:.*$", "").strip();
            if (name.isEmpty()) {
                continue;
            }
            if (!dropped) {
                dropped = true;
                continue;
            }
            out = out.replace(surface, name);
        }
        return out;
    }

    private static String firstCandidate(String list) {
        String first = list.split("/")[0].strip();
        int paren = first.indexOf('(');
        return (paren >= 0 ? first.substring(0, paren) : first).strip();
    }

    private static int tokens(String s) {
        return (int) Math.ceil(s.codePointCount(0, s.length()) * TOKENS_PER_CHAR);
    }
}
