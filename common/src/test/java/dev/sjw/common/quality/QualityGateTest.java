package dev.sjw.common.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;

import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import java.util.List;
import org.junit.jupiter.api.Test;

class QualityGateTest {

    private final QualityGate gate = new QualityGate();

    private static EntityDto linked(String surface, String name) {
        return new EntityDto(surface, "PER", "M_TEST", name, 0.99, "SINGLE", false);
    }

    private static EntityDto miss(String surface) {
        return new EntityDto(surface, "PER", null, null, 0.99, "MISS", false);
    }

    private static TranslationResponse resp(String text, EntityDto... entities) {
        return new TranslationResponse(text, List.of(entities), List.of(), null);
    }

    @Test
    void 확정_엔티티_전건_반영이면_VERIFIED() {
        var v = gate.grade(resp("강선을 부수찬으로 제수하였다.", linked("姜銑", "강선")));
        assertEquals(QualityGrade.VERIFIED, v.grade());
    }

    @Test
    void 확정_엔티티_누락이면_REJECTED_누락목록_포함() {
        var v = gate.grade(resp("아무개를 부수찬으로 제수하였다.", linked("姜銑", "강선")));
        assertEquals(QualityGrade.REJECTED, v.grade());
        assertEquals(List.of("姜銑→강선"), v.missingNames());
    }

    @Test
    void KB_MISS가_있으면_DEGRADED() {
        var v = gate.grade(resp("강선과 아무개가 아뢰었다.", linked("姜銑", "강선"), miss("無名氏")));
        assertEquals(QualityGrade.DEGRADED, v.grade());
    }

    @Test
    void 번역문_부재는_REJECTED() {
        assertEquals(QualityGrade.REJECTED, gate.grade(resp("  ")).grade());
    }

    @Test
    void 모호_후보는_확정이_아니므로_검사대상_아님() {
        var ambiguous = new EntityDto("선", "PER", null, null, 0.9, "AMBIGUOUS", true);
        var v = gate.grade(resp("임금이 전교하였다.", ambiguous));
        assertEquals(QualityGrade.VERIFIED, v.grade());
    }
}
