package dev.sjw.common.translate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

class PromptAssemblerTest {

    private final PromptAssembler assembler = new PromptAssembler();

    @Test
    void 버전은_프롬프트_파일_체크섬에서_파생된다() {
        assertTrue(assembler.version().matches("main-[0-9a-f]{8}"), assembler.version());
    }

    @Test
    void 정형문_패턴이_반드시_사용할_표현으로_주입된다() {
        String p = assembler.assemble("傳敎曰知道", List.of());
        assertTrue(p.contains("[반드시 사용할 표현]"));
        assertTrue(p.contains("전교하기를"));
    }

    @Test
    void 패턴_미검출이면_주입_블록이_없다() {
        assertFalse(assembler.assemble("平明", List.of()).contains("[반드시 사용할 표현]"));
    }

    @Test
    void 같은_입력은_같은_프롬프트() {
        // 프롬프트 결정성 — 캐시 키(M3)·회귀 비교(ADR-013)의 전제
        assertEquals(assembler.assemble("啓曰某事", List.of()),
                assembler.assemble("啓曰某事", List.of()));
    }
}
