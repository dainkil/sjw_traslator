package dev.sjw.common.translate;

import dev.sjw.common.kb.KbPerson;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/**
 * 선행 연구 프롬프트(docs/prompts.md)의 조립기. 템플릿과 정형문 패턴은 리소스 파일이다
 * (prompts/translate-main.st, prompts/positive-patterns.tsv) — Java 상수면 버전 관리·A/B·회귀
 * 비교가 성립하지 않는다 (계획서 §4.2, ADR-013).
 *
 * version()은 두 파일 바이트의 체크섬 파생값 — 프롬프트가 1바이트라도 바뀌면 버전이 갈리고,
 * 그 값이 job(prompt_version)과 응답 meta에 남아 회귀 비교의 기준선이 된다.
 * 패턴은 파일 순서 그대로 주입한다 — 프롬프트가 실행마다 달라지면 골든셋 회귀가 깨진다.
 */
@Component
public class PromptAssembler {

    private record PositivePattern(Pattern pattern, String phrase) {}

    private final List<PositivePattern> positivePatterns;
    private final String template;
    private final String version;

    public PromptAssembler() {
        byte[] templateBytes = read("prompts/translate-main.st");
        byte[] patternBytes = read("prompts/positive-patterns.tsv");
        this.template = new String(templateBytes, StandardCharsets.UTF_8);
        this.positivePatterns = parsePatterns(new String(patternBytes, StandardCharsets.UTF_8));
        this.version = "main-" + checksum8(templateBytes, patternBytes);
    }

    /** 프롬프트 파일 체크섬 파생 버전 (예: main-1a2b3c4d). */
    public String version() {
        return version;
    }

    public String assemble(String original, List<LinkedEntity> linked) {
        StringBuilder pos = new StringBuilder();
        for (PositivePattern p : positivePatterns) {
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

        return new PromptTemplate(template).render(Map.of(
                "positiveBlock", positiveBlock,
                "kbBlock", kbBlock,
                "original", original
        ));
    }

    private static byte[] read(String classpath) {
        try {
            return new ClassPathResource(classpath).getContentAsByteArray();
        } catch (IOException e) {
            throw new UncheckedIOException("프롬프트 리소스 로드 실패: " + classpath, e);
        }
    }

    private static List<PositivePattern> parsePatterns(String tsv) {
        List<PositivePattern> out = new ArrayList<>();
        for (String line : tsv.split("\n")) {
            String trimmed = line.strip();
            if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                continue;
            }
            String[] parts = trimmed.split("\t");
            if (parts.length != 2) {
                throw new IllegalStateException("positive-patterns.tsv 형식 오류: " + line);
            }
            out.add(new PositivePattern(Pattern.compile(parts[0]), parts[1]));
        }
        if (out.isEmpty()) {
            throw new IllegalStateException("positive-patterns.tsv가 비어 있음");
        }
        return List.copyOf(out);
    }

    private static String checksum8(byte[]... contents) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            for (byte[] c : contents) {
                md.update(c);
            }
            return HexFormat.of().formatHex(md.digest()).substring(0, 8);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** resolved=true면 candidates는 확정 1건, 아니면 모호 후보 목록(≤3). */
    public record LinkedEntity(String surface, List<KbPerson> candidates, boolean resolved) {}
}
