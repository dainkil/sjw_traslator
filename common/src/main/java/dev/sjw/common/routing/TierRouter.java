package dev.sjw.common.routing;

import dev.sjw.common.translate.TranslationDtos.EntityDto;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/**
 * 난이도 티어 판정기 (§5.1, ADR-010). 결정론적이고 LLM 호출 0회다 —
 * 입력이 되는 신호가 파이프라인에서 이미 계산돼 있기 때문이다.
 *
 * <p><b>규칙은 계획서 §5.1 표를 실측으로 고친 것이다</b> (전수 62,056문장, M4-S1):
 * <ul>
 *   <li><b>T2 = 동명이인 모호만.</b> 원안은 "KB 미매칭 <i>또는</i> 모호"였는데, 그러면 29.86%가
 *       상위 모델로 가서 quota 몫(3.8%)을 8배 초과한다. 더 중요한 것은 <b>품질 논리가 다르다</b>는
 *       점이다 — MISS는 역색인에 인물이 없다는 뜻이고, 모델을 올려도 그 인물에 대해 아는 바가
 *       늘지 않는다(지식원은 KB지 LLM이 아니다, ADR-006의 전제와 같다). 모호는 후보가 이미
 *       주입돼 있고 고르는 일이 추론이므로 상위 모델이 더 잘할 여지가 있다. 모호만 두면 1.83%다.
 *   <li><b>T0 = 엔티티 0개 + 정형문 패턴.</b> NER 단독으로는 안 된다 — M1에서 인물이 있는 문장도
 *       전 토큰 O 예측이 나오는 사례가 확인됐다(계획서 §10 M4). 패턴 결합이 그 방어다. 실측 5.90%.
 *   <li><b>T1 = 나머지 전부.</b> 원안 표는 문장의 35.87%를 어느 티어로도 보내지 않았다
 *       (엔티티 0+패턴 없음 / PER 없고 LOC·DAT만 / PER 3개 이상 전건 확정). 기본을 T1로 두어
 *       미정의 구간을 없앤다 — 판정되지 않는 문장이 있으면 라우터가 아니다.
 * </ul>
 *
 * <p><b>T0와 T1은 지금 같은 모델로 간다.</b> 무료 티어에서 flash-lite가 최대 quota 보유자라
 * "더 싼 곳으로 하향"할 대상이 없기 때문이다. 그래도 티어를 구분해 기록하는 이유는
 * ① §9.1 {@code translation.tier.distribution}의 분모가 되고 ② gemma-4 등의 quota가 실측되면
 * T0의 목적지가 생긴다. 지금 없는 효과를 있는 척하지 않기 위해 이 점을 명시한다.
 */
@Component
public class TierRouter {

    /**
     * 정형문 구조 표지 — <b>프롬프트의 어휘 목록과 분리된 리소스</b>다.
     *
     * <p>{@code prompts/positive-patterns.tsv}를 재사용하지 않는 이유는 두 가지다. 목적이 다르다
     * (그쪽은 "번역문에 반드시 쓸 어휘", 이쪽은 "이 문장이 정례 항목인가")는 것이 첫째고, 실제로
     * 누락이 있었다는 것이 둘째다 — 어휘 목록에는 {@code 傳曰}(전체 문장의 31.5%)·{@code 答曰}(25.0%)이
     * 없어서 T0 판정이 5.90%에 머물렀다. 분리한 목록으로는 13.02%다 (전수 실측, M4-S1).
     * 묶어두면 프롬프트를 고칠 때 라우팅이 조용히 바뀌는 문제도 남는다.
     */
    private static final String PATTERN_RESOURCE = "routing/formulaic-patterns.tsv";

    public record Decision(Tier tier, RoutingSignals signals, String reason) {}

    private final List<Pattern> formulaic;

    public TierRouter() {
        this.formulaic = loadPatterns();
    }

    public Decision classify(String sourceText, List<EntityDto> entities) {
        RoutingSignals s = extract(sourceText, entities);
        if (s.ambiguous() > 0) {
            return new Decision(Tier.T2, s, "동명이인 모호 " + s.ambiguous() + "건 — 문맥 판단이 필요하다");
        }
        if (s.entities() == 0 && s.formulaic()) {
            return new Decision(Tier.T0, s, "엔티티 0개 + 정형문 패턴");
        }
        return new Decision(Tier.T1, s, describeT1(s));
    }

    public RoutingSignals extract(String sourceText, List<EntityDto> entities) {
        int per = 0, loc = 0, dat = 0, confirmed = 0, miss = 0, ambiguous = 0;
        for (EntityDto e : entities) {
            switch (e.type() == null ? "" : e.type()) {
                case "PER" -> per++;
                case "LOC" -> loc++;
                case "DAT" -> dat++;
                default -> { }
            }
            if (!"PER".equals(e.type())) {
                continue;
            }
            if (e.kbId() != null) {
                confirmed++;
            } else if ("MISS".equals(e.linkStage())) {
                miss++;
            } else if ("AMBIGUOUS".equals(e.linkStage())) {
                ambiguous++;
            }
        }
        boolean matched = sourceText != null
                && formulaic.stream().anyMatch(p -> p.matcher(sourceText).find());
        return new RoutingSignals(entities.size(), per, loc, dat, confirmed, miss, ambiguous, matched);
    }

    /** T1은 기본값이므로 "왜 T1인가"가 로그·원장에서 읽혀야 한다. */
    private static String describeT1(RoutingSignals s) {
        if (s.kbMiss() > 0) {
            return "KB 미등재 " + s.kbMiss() + "건 — 모델을 올려도 없는 지식은 생기지 않는다 (KB 확장 대상)";
        }
        if (s.per() == 0) {
            return s.entities() == 0 ? "엔티티 0개, 정형문 패턴 없음" : "PER 없음 (LOC·DAT만)";
        }
        return "확정 PER " + s.confirmed() + "건";
    }

    private static List<Pattern> loadPatterns() {
        byte[] raw;
        try {
            raw = new ClassPathResource(PATTERN_RESOURCE).getContentAsByteArray();
        } catch (IOException e) {
            throw new UncheckedIOException("정형문 패턴 로드 실패: " + PATTERN_RESOURCE, e);
        }
        List<Pattern> out = new ArrayList<>();
        for (String line : new String(raw, StandardCharsets.UTF_8).split("\n")) {
            String t = line.strip();
            if (t.isEmpty() || t.startsWith("#")) {
                continue;
            }
            out.add(Pattern.compile(t.split("\t")[0]));
        }
        if (out.isEmpty()) {
            throw new IllegalStateException(PATTERN_RESOURCE + "가 비어 있음");
        }
        return List.copyOf(out);
    }
}
