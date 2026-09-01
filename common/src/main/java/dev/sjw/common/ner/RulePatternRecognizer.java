package dev.sjw.common.ner;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 규칙 기반 축소판 NER — degrade 경로 + "KB 주입 효과" A/B의 대조군.
 *
 * 골든셋 실측 (docs/benchmarks.md): PER recall 27.2%, precision 62.3% —
 * ONNX(recall 100%)와의 격차 자체가 이 구현의 존재 이유다. 규칙을 늘려 성능을 좇지 않는다.
 *
 * 규칙 3종 (승정원일기 정형문 기반, 골든셋으로 튜닝):
 *  R1 제수 기사: 以◯◯爲◯◯ 의 앞 2~3자
 *  R2 성씨 + 1~2자 + 행위동사(曰/啓/疏/箚/辭/進/退/對/白)
 *  R3 관직명 직후의 2~3자 성명 (문장 경계 앞)
 */
public class RulePatternRecognizer implements EntityRecognizer {

    private static final String HAN = "[\\u4E00-\\u9FFF]";
    private static final Pattern R1_APPOINT = Pattern.compile("以(" + HAN + "{2,3}?)爲");
    private static final Pattern R2_SPEECH = Pattern.compile(
            "([金李朴崔鄭姜趙尹張林韓吳申權黃安宋柳洪全高文孫梁裵曺白許劉南沈盧河兪成車具郭禹朱任田閔辛]"
                    + HAN + "{1,2})(?=[,、]?[曰啓疏箚辭進退對白])");
    private static final Pattern R3_OFFICE = Pattern.compile(
            "(?:承旨|修撰|正言|持平|掌令|獻納|校理|應敎|副提學|大司諫|大司憲|判書|參判|參議|佐郞|正郞"
                    + "|都事|注書|檢閱|奉敎|待敎|說書|司書|弼善|輔德|翊善)(" + HAN + "{2,3})(?=[,、。]|$)");
    private static final List<Pattern> RULES = List.of(R1_APPOINT, R2_SPEECH, R3_OFFICE);

    /** 규칙 기반은 신뢰도 추정이 없다 — 고정값. HTTP 어댑터의 min_score(0.5)와 같은 선. */
    private static final double FIXED_SCORE = 0.5;

    @Override
    public String id() {
        return "rule-v1";
    }

    @Override
    public List<NerEntity> extract(String text) {
        List<NerEntity> out = new ArrayList<>();
        for (Pattern rule : RULES) {
            Matcher m = rule.matcher(text);
            while (m.find()) {
                if (!overlaps(out, m.start(1), m.end(1))) {
                    out.add(new NerEntity(m.group(1), "PER", m.start(1), m.end(1), FIXED_SCORE));
                }
            }
        }
        out.sort((a, b) -> Integer.compare(a.start(), b.start()));
        return out;
    }

    private static boolean overlaps(List<NerEntity> kept, int start, int end) {
        for (NerEntity e : kept) {
            if (start < e.end() && e.start() < end) {
                return true;
            }
        }
        return false;
    }
}
