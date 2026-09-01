package dev.sjw.common.cache;

import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.util.TextHash;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Component;

/**
 * §5.2 템플릿 슬롯 캐싱의 도메인 로직 (ADR-009): 원문 슬롯화 → template_hash,
 * 번역문 템플릿화(적재), 마커 재주입 + 조사 보정(히트).
 *
 * 슬롯 대상은 <b>링크 확정 PER만</b>이다 — 재주입의 안전성은 "이 자리에 무엇이 들어가야
 * 하는가"를 결정론적으로 아는 데서 나오는데, 그 답(확정 한글명)을 가진 엔티티가 PER뿐이다.
 * POS/DAT는 결정론적 한국어 대역이 없어 문면 그대로 템플릿에 남는다 (확장 조건은 ADR-009).
 */
@Component
public class TemplateSlotter {

    public record Slot(String marker, String surface, String resolvedName) {}

    public record SlottedSource(String template, List<Slot> slots) {}

    /** 원문 슬롯화. 링크 확정 PER이 하나도 없으면 empty — L2의 대상이 아니다. */
    public Optional<SlottedSource> slotSource(String sourceText, List<EntityDto> entities) {
        Map<String, String> confirmed = new LinkedHashMap<>(); // surface → 확정 한글명
        for (EntityDto e : entities) {
            if ("PER".equals(e.type()) && e.kbId() != null
                    && e.resolvedName() != null && !e.resolvedName().isBlank()
                    && sourceText.contains(e.surface())) {
                confirmed.putIfAbsent(e.surface(), e.resolvedName());
            }
        }
        if (confirmed.isEmpty()) {
            return Optional.empty();
        }

        // 슬롯 번호는 원문 내 첫 등장 위치 순 — 구조가 같은 두 문장이 같은 번호 배열을 갖는다
        List<String> byPosition = confirmed.keySet().stream()
                .sorted(Comparator.comparingInt(sourceText::indexOf))
                .toList();
        Map<String, Slot> slotBySurface = new LinkedHashMap<>();
        List<Slot> slots = new ArrayList<>();
        for (int i = 0; i < byPosition.size(); i++) {
            String surface = byPosition.get(i);
            Slot s = new Slot("⟪PER" + (i + 1) + "⟫", surface, confirmed.get(surface));
            slotBySurface.put(surface, s);
            slots.add(s);
        }

        // 치환은 긴 표면형부터 — 한 표면형이 다른 표면형의 부분 문자열일 때 오염을 막는다
        String template = sourceText;
        List<String> byLengthDesc = confirmed.keySet().stream()
                .sorted(Comparator.comparingInt(String::length).reversed())
                .toList();
        for (String surface : byLengthDesc) {
            template = template.replace(surface, slotBySurface.get(surface).marker());
        }
        return Optional.of(new SlottedSource(template, List.copyOf(slots)));
    }

    /** L2 캐시 키의 재료 — 슬롯화된 원문의 정규화 해시. */
    public String templateHash(SlottedSource src) {
        return TextHash.normalizedHash(src.template());
    }

    /**
     * 번역문 템플릿화 (적재 시). 각 슬롯의 확정 한글명 <b>전체형</b>이 번역문에 있어야만
     * 성립한다 — 게이트(§5.4)는 이름부 일치("문회")도 반영으로 인정하지만, 이름부만 있는
     * 번역은 인명 구간을 결정론적으로 특정할 수 없어 템플릿으로 만들지 않는다 (보수적 적재).
     */
    public Optional<String> templateizeTranslation(String translation, SlottedSource src) {
        if (translation == null || translation.isBlank()) {
            return Optional.empty();
        }
        String template = translation;
        List<Slot> byNameLengthDesc = src.slots().stream()
                .sorted(Comparator.comparingInt((Slot s) -> s.resolvedName().length()).reversed())
                .toList();
        for (Slot s : byNameLengthDesc) {
            if (!template.contains(s.resolvedName())) {
                return Optional.empty();
            }
            template = template.replace(s.resolvedName(), s.marker());
        }
        return Optional.of(template);
    }

    /**
     * 히트 시 재주입: 캐시된 번역 템플릿의 마커를 새 문장의 확정 한글명으로 치환하고
     * 마커 바로 뒤의 조사를 받침에 맞게 보정한다. 구조 불일치(마커 누락·잔존)는 empty —
     * 호출자는 MISS로 취급해 전체 파이프라인으로 fallback한다 (M3 수용 기준).
     */
    public Optional<String> reinject(String translationTemplate, SlottedSource newSource) {
        String out = translationTemplate;
        for (Slot s : newSource.slots()) {
            if (!out.contains(s.marker())) {
                return Optional.empty();
            }
            out = replaceWithParticleFix(out, s.marker(), s.resolvedName());
        }
        if (out.contains("⟪")) {
            return Optional.empty(); // 새 문장에 없는 슬롯이 템플릿에 남아 있다
        }
        return Optional.of(out);
    }

    // ── 조사 보정 ──────────────────────────────────────────────────────────

    private record ParticleFix(String replacement, int consumed) {}

    private static String replaceWithParticleFix(String text, String marker, String name) {
        StringBuilder sb = new StringBuilder();
        boolean batchim = hasBatchim(name);
        int from = 0;
        int idx;
        while ((idx = text.indexOf(marker, from)) >= 0) {
            sb.append(text, from, idx).append(name);
            from = idx + marker.length();
            ParticleFix fix = fixParticle(text, from, batchim);
            sb.append(fix.replacement());
            from += fix.consumed();
        }
        sb.append(text.substring(from));
        return sb.toString();
    }

    /**
     * 마커 바로 뒤 조사만 본다: 이/가, 을/를, 은/는, 과/와, 이라/라.
     * 단음절 조사는 그 뒤가 한글 음절이면 조사가 아니라 다음 단어의 첫 글자일 수 있어
     * (예: "○○이조판서") 경계(공백·구두점·문장 끝)일 때만 보정한다.
     */
    private static ParticleFix fixParticle(String text, int pos, boolean batchim) {
        if (pos >= text.length()) {
            return new ParticleFix("", 0);
        }
        if (text.startsWith("이라", pos)) {
            return new ParticleFix(batchim ? "이라" : "라", 2);
        }
        char c = text.charAt(pos);
        String fixed = switch (c) {
            case '이', '가' -> batchim ? "이" : "가";
            case '을', '를' -> batchim ? "을" : "를";
            case '은', '는' -> batchim ? "은" : "는";
            case '과', '와' -> batchim ? "과" : "와";
            default -> null;
        };
        if (fixed == null || !atWordBoundary(text, pos + 1)) {
            return new ParticleFix("", 0);
        }
        return new ParticleFix(fixed, 1);
    }

    private static boolean atWordBoundary(String text, int pos) {
        if (pos >= text.length()) {
            return true;
        }
        char next = text.charAt(pos);
        return !(next >= 0xAC00 && next <= 0xD7A3);
    }

    private static boolean hasBatchim(String name) {
        char last = name.charAt(name.length() - 1);
        if (last < 0xAC00 || last > 0xD7A3) {
            return false;
        }
        return (last - 0xAC00) % 28 != 0;
    }
}
