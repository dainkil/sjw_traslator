package dev.sjw.common.translate;

import dev.sjw.common.kb.KbPerson;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.stereotype.Component;

/**
 * 선행 연구 프롬프트(docs/prompts.md)의 PromptTemplate 구조화.
 * 정형문 패턴·문체 표·예시는 연구 원문 그대로 (research/04_ablation/run_kbinject.py).
 * 패턴은 순서 보장 List로 유지한다 — 프롬프트가 실행마다 달라지면 골든셋 회귀(ADR-013)가 깨진다.
 */
@Component
public class PromptAssembler {

    private record PositivePattern(Pattern pattern, String phrase) {}

    private static final List<PositivePattern> POSITIVE_PATTERNS = List.of(
            new PositivePattern(Pattern.compile("傳敎曰|下敎曰|傳旨"), "전교하기를"),
            new PositivePattern(Pattern.compile("啓曰|啓言|狀啓"), "아뢰기를 / 장계하기를"),
            new PositivePattern(Pattern.compile("允許|允從|許之(?!諫)"), "윤허하다"),
            new PositivePattern(Pattern.compile("不許|不允"), "윤허하지 않다"),
            new PositivePattern(Pattern.compile("拜.*爲|除授|落點"), "제수하다"),
            new PositivePattern(Pattern.compile("行幸|臨幸"), "거둥하다"),
            new PositivePattern(Pattern.compile("還宮"), "환궁하다"),
            new PositivePattern(Pattern.compile("書啓"), "서계하기를"),
            new PositivePattern(Pattern.compile("馳啓"), "치계하기를")
    );

    private static final String TEMPLATE = """
            당신은 승정원일기 전문 번역가입니다. 원문 한문을 정확하고 자연스러운 현대 한국어로 번역합니다.

            [번역 원칙]
            1. 종결어미: -하였다 사용 (-했다 금지)
            2. 왕 지칭: 상(上) 또는 전하
            3. 신하 자칭: 신(臣) 또는 소신
            4. 인용 형식: ~하기를, "..." 하였다
            5. 관직·인명은 원문 음독

            [현대어 X → 실록 문체 O]
              · 임명하다 X → 제수하다 O
              · 허락하다 X → 윤허하다 O
              · 허락하지 않다 X → 윤허하지 않다 O
              · 행차하다 X → 거둥하다 O
              · 돌아오다 / 귀환하다 X → 환궁하다 O
              · 보고하기를 (지방) X → 장계하기를 / 서계하기를 O
              · 말씀하기를 / 명령하기를 X → 전교하기를 / 하교하기를 O

            [번역 예시]
            - 홍문관이 아뢰기를, "정경세가 현재 상주에 있으니, 올라오도록 하유하소서." 하니, 윤허한다고 전교하였다.
            - 전교하기를, "영의정 이원익에게 사관을 보내어 전유하라." 하였다.
            - 봉림대군에게 처음 직임을 제수하였다.
            - 심양에서 재신이 장계하기를, "이달 9일에 왕세자가 서쪽으로 행차합니다." 하였다.
            - 상이 혼궁 소상제를 친히 지내기 위해 거둥하였다.
            - 비변사가 서계하기를, "변경의 사정이 긴박하오니 속히 군병을 증파하소서." 하였다.
            - 이날 밤에 큰 바람이 불고 우레와 번개가 쳤다.
            {positiveBlock}{kbBlock}
            번역이 불확실한 구간(KB에 없는 인명, 판독 모호 한자 등)은 uncertainSpans에 사유와 함께 보고하세요.
            위 원칙과 예시의 문체로 다음 한문을 번역하세요:

            {original}
            """;

    public String assemble(String original, List<LinkedEntity> linked) {
        StringBuilder pos = new StringBuilder();
        for (PositivePattern p : POSITIVE_PATTERNS) {
            if (p.pattern().matcher(original).find()) {
                pos.append("  · ").append(p.phrase()).append('\n');
            }
        }
        String positiveBlock = pos.isEmpty() ? "" : "\n[반드시 사용할 표현]\n" + pos;

        StringBuilder kb = new StringBuilder();
        for (LinkedEntity e : linked) {
            if (e.resolved()) {
                KbPerson p = e.candidates().getFirst();
                kb.append("  · ").append(e.surface()).append(" → ").append(p.hangulName());
                if (p.offices() != null && !p.offices().isEmpty()) {
                    kb.append("  (관직: ").append(p.offices().getFirst()).append(')');
                }
                kb.append('\n');
            } else {
                // 모호 케이스: 후보를 모두 주입하고 판단을 LLM에 넘긴다 (계획서 §7 — Tool Calling 배제의 전제)
                kb.append("  · ").append(e.surface()).append(" → 동명이인 후보 중 문맥으로 판단: ");
                kb.append(String.join(" / ", e.candidates().stream()
                        .map(p -> p.hangulName()
                                + (p.activeFrom() != null ? "(활동 " + p.activeFrom() + "~" : "(")
                                + (p.offices() != null && !p.offices().isEmpty()
                                        ? ", " + p.offices().getFirst() : "")
                                + ")")
                        .toList()));
                kb.append('\n');
            }
        }
        String kbBlock = kb.isEmpty() ? "" : "\n[등장 인물 한자→한글]\n" + kb;

        return new PromptTemplate(TEMPLATE).render(Map.of(
                "positiveBlock", positiveBlock,
                "kbBlock", kbBlock,
                "original", original
        ));
    }

    /** resolved=true면 candidates는 확정 1건, 아니면 모호 후보 목록(≤3). */
    public record LinkedEntity(String surface, List<KbPerson> candidates, boolean resolved) {}
}
