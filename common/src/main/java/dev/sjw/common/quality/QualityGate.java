package dev.sjw.common.quality;

import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * 런타임 품질 게이트 (§5.4-(1), ADR-019). KB로 링크가 <b>확정</b>된 인물의 한글명이
 * 번역문에 실제로 등장했는지 결정론적으로 검사한다 — 이 프로젝트만 보유한 자동 검증 신호.
 * LLM 추가 호출 0회, quota 소모 0.
 *
 * 오탐 주의: 번역이 이형 표기(호·시호·관직 대칭)를 쓰면 정상인데 REJECTED가 난다.
 * 골든셋 전문가 번역 대상 오탐률이 선측정되어 있다 (QualityGateGoldensetTest, docs/benchmarks.md) —
 * 측정 없이 상향 라우팅을 켜지 않는다는 계획 원칙의 이행.
 */
@Component
public class QualityGate {

    public record Verdict(QualityGrade grade, List<String> missingNames) {}

    public Verdict grade(TranslationResponse resp) {
        String text = resp.translatedText();
        if (text == null || text.isBlank()) {
            return new Verdict(QualityGrade.REJECTED, List.of());
        }

        List<String> missing = new ArrayList<>();
        boolean kbMiss = false;
        for (EntityDto e : resp.entities()) {
            if (e.kbId() != null && e.resolvedName() != null && !e.resolvedName().isBlank()) {
                if (!nameReflected(text, e.resolvedName())) {
                    missing.add(e.surface() + "→" + e.resolvedName());
                }
            } else if ("MISS".equals(e.linkStage())) {
                kbMiss = true;
            }
        }
        if (!missing.isEmpty()) {
            return new Verdict(QualityGrade.REJECTED, List.copyOf(missing));
        }
        return new Verdict(kbMiss ? QualityGrade.DEGRADED : QualityGrade.VERIFIED, List.of());
    }

    /**
     * 이형 표기 보정 (골든셋 오탐 실측에서 도출): 전문가 번역은 성을 생략하고 이름부만
     * 쓰기도 한다 (예: 정문회 → "문회"). 전체 이름 또는 이름부(2자 이상)가 있으면 반영으로 본다.
     * 이름부 1자(예: 윤공→"공")는 우연 일치가 많아 허용하지 않는다.
     */
    private static boolean nameReflected(String text, String name) {
        if (text.contains(name)) {
            return true;
        }
        String givenPart = name.length() >= 3 ? name.substring(1) : null;
        return givenPart != null && givenPart.length() >= 2 && text.contains(givenPart);
    }
}
