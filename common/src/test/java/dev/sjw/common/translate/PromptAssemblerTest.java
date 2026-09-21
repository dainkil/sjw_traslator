package dev.sjw.common.translate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.DefaultResourceLoader;

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

    @Test
    void 다른_템플릿_파일을_주면_버전이_갈린다(@TempDir Path dir) throws IOException {
        // M3.5-S2 ablation의 전제 — 변형은 file: 리소스로 들어오고 prompt_version이 저절로 달라진다
        Path variant = dir.resolve("variant.st");
        Files.writeString(variant, "변형 프롬프트\n{positiveBlock}{kbBlock}\n{original}\n");
        var v = new PromptAssembler(new DefaultResourceLoader(), variant.toUri().toString(),
                PromptAssembler.DEFAULT_PATTERNS);
        assertNotEquals(assembler.version(), v.version());
        assertTrue(v.version().matches("main-[0-9a-f]{8}"), v.version());
        assertTrue(v.assemble("啓曰某事", List.of()).startsWith("변형 프롬프트"));
    }

    @Test
    void 같은_바이트면_경로가_달라도_같은_버전(@TempDir Path dir) throws IOException {
        // 버전은 위치가 아니라 내용에서 나온다 — 대조군(V0)을 file:로 띄워도 생산 버전과 동일해야 한다
        Path copy = dir.resolve("copy.st");
        Files.write(copy, new ClassPathResource("prompts/translate-main.st").getContentAsByteArray());
        var v = new PromptAssembler(new DefaultResourceLoader(), copy.toUri().toString(),
                PromptAssembler.DEFAULT_PATTERNS);
        assertEquals(assembler.version(), v.version());
    }
}
