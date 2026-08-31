package dev.sjw.api.kb;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 인조 연간 인물 KB — in-memory 상주 (ADR-004).
 * 링킹 로직은 kb/data_ContextInjection.py의 이식 (ADR-015):
 * 역색인 후보 생성 → 활동시기 필터 → 관직-문맥 매칭.
 */
@Component
public class KnowledgeBase {

    private static final Logger log = LoggerFactory.getLogger(KnowledgeBase.class);
    private static final Pattern PAREN = Pattern.compile("\\(.*?\\)");
    private static final Pattern HANJA_IN_PAREN = Pattern.compile("\\((.*?)\\)");
    private static final int MAX_AMBIGUOUS = 3;

    private final Map<String, KbPerson> idLookup;
    private final Map<String, List<String>> invertedIndex;
    private final String version;

    public KnowledgeBase(@Value("${sjw.kb.dir}") String kbDir,
                         @Value("${sjw.kb.version}") String version) throws IOException {
        ObjectMapper om = new ObjectMapper();
        Path dir = Path.of(kbDir);
        this.idLookup = om.readValue(dir.resolve("id_lookup_injo.json").toFile(),
                new TypeReference<>() {});
        this.invertedIndex = om.readValue(dir.resolve("inverted_index_injo.json").toFile(),
                new TypeReference<>() {});
        this.version = version;
        log.info("KB 로드: 인물 {}명, 역색인 {}키 (version={})",
                idLookup.size(), invertedIndex.size(), version);
    }

    public String version() {
        return version;
    }

    public KbPerson person(String id) {
        return idLookup.get(id);
    }

    public LinkResult link(String mention, int currentYear, String contextText) {
        List<String> candidates = invertedIndex.get(mention);
        if (candidates == null || candidates.isEmpty()) {
            return LinkResult.miss();
        }
        if (candidates.size() == 1) {
            return new LinkResult(LinkResult.Stage.SINGLE, candidates);
        }

        List<String> timeFiltered = candidates.stream()
                .filter(id -> idLookup.get(id) != null
                        && idLookup.get(id).activeFromOrZero() <= currentYear)
                .toList();
        if (timeFiltered.size() == 1) {
            return new LinkResult(LinkResult.Stage.TIME, timeFiltered);
        }

        // Python 원본은 괄호(한자)를 벗긴 한글 관직명만 문맥과 대조한다.
        // 서빙 파이프라인의 문맥은 한문 원문이므로 괄호 안 한자 표기도 함께 대조한다
        // (원본의 상위 호환 — 한글 문맥이 오면 원본과 동일하게 동작).
        List<String> jobFiltered = new ArrayList<>();
        for (String id : timeFiltered) {
            KbPerson p = idLookup.get(id);
            List<String> offices = p.offices() == null ? List.of() : p.offices();
            for (String job : offices) {
                String hangul = PAREN.matcher(job).replaceAll("").strip();
                var hanja = HANJA_IN_PAREN.matcher(job);
                boolean hit = (!hangul.isEmpty() && contextText.contains(hangul))
                        || (hanja.find() && !hanja.group(1).isBlank()
                            && contextText.contains(hanja.group(1)));
                if (hit) {
                    jobFiltered.add(id);
                    break;
                }
            }
        }
        if (jobFiltered.size() == 1) {
            return new LinkResult(LinkResult.Stage.OFFICE, jobFiltered);
        }

        List<String> remaining = jobFiltered.isEmpty()
                ? timeFiltered.subList(0, Math.min(MAX_AMBIGUOUS, timeFiltered.size()))
                : jobFiltered;
        return new LinkResult(LinkResult.Stage.AMBIGUOUS, List.copyOf(remaining));
    }
}
