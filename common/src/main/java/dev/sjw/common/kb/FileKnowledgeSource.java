package dev.sjw.common.kb;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 파일 기반 인물 KB — in-memory 상주 (ADR-004). name으로 왕대를 고른다
 * (id_lookup_{name}.json / inverted_index_{name}.json — injo, jeongjo 커밋됨).
 * 링킹 로직은 kb/data_ContextInjection.py의 이식 (ADR-015):
 * 역색인 후보 생성 → 활동시기 필터 → 관직-문맥 매칭.
 *
 * version은 데이터 파일 체크섬에서 파생된다 — M3 캐시 무효화가 이 값을 믿으려면
 * "데이터가 바뀌면 반드시 바뀌는" 성질이 필요하고, 자유 문자열에는 그것이 없다.
 */
public class FileKnowledgeSource implements KnowledgeSource {

    private static final Logger log = LoggerFactory.getLogger(FileKnowledgeSource.class);
    private static final Pattern PAREN = Pattern.compile("\\(.*?\\)");
    private static final Pattern HANJA_IN_PAREN = Pattern.compile("\\((.*?)\\)");
    private static final int MAX_AMBIGUOUS = 3;

    private final Map<String, KbPerson> idLookup;
    private final Map<String, List<String>> invertedIndex;
    private final String version;

    public FileKnowledgeSource(String kbDir, String name) throws IOException {
        ObjectMapper om = new ObjectMapper();
        Path lookupFile = Path.of(kbDir).resolve("id_lookup_" + name + ".json");
        Path indexFile = Path.of(kbDir).resolve("inverted_index_" + name + ".json");
        this.idLookup = om.readValue(lookupFile.toFile(), new TypeReference<>() {});
        this.invertedIndex = om.readValue(indexFile.toFile(), new TypeReference<>() {});
        this.version = name + "-" + checksum8(lookupFile, indexFile);
        log.info("KB 로드: 인물 {}명, 역색인 {}키 (version={})",
                idLookup.size(), invertedIndex.size(), version);
    }

    /** 두 데이터 파일 바이트의 SHA-256 앞 8자리 — 파일이 1바이트라도 다르면 버전이 갈린다. */
    private static String checksum8(Path... files) throws IOException {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            for (Path f : files) {
                md.update(Files.readAllBytes(f));
            }
            return HexFormat.of().formatHex(md.digest()).substring(0, 8);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    public String version() {
        return version;
    }

    @Override
    public KbPerson person(String id) {
        return idLookup.get(id);
    }

    @Override
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
