package dev.sjw.common.quality;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.common.kb.FileKnowledgeSource;
import dev.sjw.common.kb.LinkResult;
import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/**
 * 게이트 오탐률 선측정 (§5.4 "측정 없이 켜지 않는다").
 *
 * 골든셋의 reference는 전문가 번역 = 정답이다. 정답 번역을 게이트에 넣어 REJECTED가 나오면
 * 그것이 오탐(이형 표기: 호·시호·관직 대칭 등)이다. 이 비율이 티어 승격(quota 소모)의
 * 예상 낭비율 상한이 된다. 실측치는 docs/benchmarks.md에 기록.
 */
class QualityGateGoldensetTest {

    @Test
    void 전문가_번역_대상_오탐률_측정() throws Exception {
        ObjectMapper om = new ObjectMapper();
        JsonNode gt = om.readTree(Files.readString(Path.of("..", "eval", "ner_groundtruth_300.json")));
        JsonNode ev = om.readTree(Files.readString(Path.of("..", "eval", "eval300_1925.json")));
        var kb = new FileKnowledgeSource("../kb", "injo");
        var gate = new QualityGate();

        Map<String, JsonNode> rows = new HashMap<>();
        ev.get("corpus").forEach(r -> rows.put(r.get("id").asText(), r));

        int sentencesWithConfirmed = 0;
        int falsePositives = 0;
        List<String> examples = new ArrayList<>();
        var ids = gt.fieldNames();
        while (ids.hasNext()) {
            String id = ids.next();
            JsonNode row = rows.get(id);
            if (row == null || gt.get(id).isEmpty()) {
                continue;
            }
            String original = row.get("original").asText();
            String reference = row.get("reference").asText();
            int year = 1623 + Integer.parseInt(id.substring(5, 7)) - 1; // 인조 즉위 1623 (BatchController와 동일 규칙)

            List<EntityDto> dtos = new ArrayList<>();
            for (JsonNode e : gt.get(id)) {
                if (!"PER".equals(e.get(0).asText())) {
                    continue;
                }
                LinkResult r = kb.link(e.get(1).asText(), year, original);
                if (r.resolvedId() != null) {
                    dtos.add(new EntityDto(e.get(1).asText(), "PER", r.resolvedId(),
                            kb.person(r.resolvedId()).hangulName(), 1.0, r.stage().name(), false));
                }
            }
            if (dtos.isEmpty()) {
                continue;
            }
            sentencesWithConfirmed++;
            var verdict = gate.grade(new TranslationResponse(reference, dtos, List.of(), null));
            if (verdict.grade() == QualityGrade.REJECTED) {
                falsePositives++;
                if (examples.size() < 5) {
                    examples.add(id + " " + verdict.missingNames());
                }
            }
        }
        double fpRate = falsePositives / (double) sentencesWithConfirmed;
        System.out.printf("gate goldenset: 확정보유 문장=%d 오탐=%d 오탐률=%.3f%n",
                sentencesWithConfirmed, falsePositives, fpRate);
        examples.forEach(x -> System.out.println("  오탐 예: " + x));

        assertTrue(sentencesWithConfirmed >= 50, "표본 부족: " + sentencesWithConfirmed);
        // 회귀 하한: 실측(2026-09-01) 기준 고정. 게이트/KB 변경으로 오탐이 급증하면 여기서 잡힌다.
        assertTrue(fpRate <= 0.15, "오탐률이 실측 상한(0.15)을 초과: " + fpRate);
    }
}
