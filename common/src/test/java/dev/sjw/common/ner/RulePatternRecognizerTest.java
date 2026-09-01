package dev.sjw.common.ner;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;

class RulePatternRecognizerTest {

    private final RulePatternRecognizer rule = new RulePatternRecognizer();

    @Test
    void appointmentPatternExtractsPerson() {
        List<NerEntity> out = rule.extract("以姜銑爲副修撰");
        assertEquals(1, out.size());
        assertEquals("姜銑", out.get(0).surface());
        assertEquals("PER", out.get(0).type());
        assertEquals(1, out.get(0).start());
    }

    @Test
    void surnameSpeechActPatternExtractsPerson() {
        List<NerEntity> out = rule.extract("領議政李元翼進曰臣以老病");
        assertTrue(out.stream().anyMatch(e -> e.surface().equals("李元翼")));
    }

    @Test
    void noEntityYieldsEmptyListNotError() {
        assertEquals(List.of(), rule.extract("傳曰知道"));
    }

    /**
     * 골든셋 실측 — 축소판의 성능 하한 회귀 방지. 기대치가 아니라 실측치(recall 27.2%,
     * precision 62.3%, 2026-09-01)의 하한이다. 이 수치가 ONNX(recall 100%) 대비
     * "KB 주입 효과 A/B"의 대조군 격차를 정의한다 (docs/benchmarks.md).
     */
    @Test
    void goldensetRecallAndPrecisionFloor() throws Exception {
        ObjectMapper om = new ObjectMapper();
        JsonNode gt = om.readTree(Files.readString(Path.of("..", "eval", "ner_groundtruth_300.json")));
        JsonNode ev = om.readTree(Files.readString(Path.of("..", "eval", "eval300_1925.json")));

        Map<String, String> texts = new HashMap<>();
        ev.get("corpus").forEach(r -> texts.put(r.get("id").asText(), r.get("original").asText()));

        int tp = 0;
        int fp = 0;
        int fn = 0;
        var ids = gt.fieldNames();
        while (ids.hasNext()) {
            String id = ids.next();
            Set<String> gold = new HashSet<>();
            gt.get(id).forEach(e -> {
                if ("PER".equals(e.get(0).asText())) {
                    gold.add(e.get(1).asText());
                }
            });
            Set<String> pred = new HashSet<>();
            rule.extract(texts.getOrDefault(id, "")).forEach(e -> pred.add(e.surface()));

            for (String p : pred) {
                if (gold.contains(p)) {
                    tp++;
                } else {
                    fp++;
                }
            }
            for (String g : gold) {
                if (!pred.contains(g)) {
                    fn++;
                }
            }
        }
        double recall = tp / (double) (tp + fn);
        double precision = tp / (double) (tp + fp);
        System.out.printf("rule-v1 goldenset: tp=%d fp=%d fn=%d recall=%.3f precision=%.3f%n",
                tp, fp, fn, recall, precision);
        assertTrue(recall >= 0.20, "recall 하한(0.20) 미달: " + recall);
        assertTrue(precision >= 0.50, "precision 하한(0.50) 미달: " + precision);
    }
}
