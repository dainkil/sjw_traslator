package dev.sjw.common.kb;

import java.io.IOException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** KB 구현 선택 — 설정만으로 교체한다 (M2.5 수용 기준 1: 인조→정조 코드 수정 0줄). */
@Configuration
public class KbConfig {

    private static final Logger log = LoggerFactory.getLogger(KbConfig.class);

    @Bean
    public KnowledgeSource knowledgeSource(
            @Value("${sjw.kb.mode:file}") String mode,
            @Value("${sjw.kb.dir}") String dir,
            @Value("${sjw.kb.name:injo}") String name) throws IOException {
        KnowledgeSource kb = switch (mode) {
            case "file" -> new FileKnowledgeSource(dir, name);
            case "noop" -> new NoOpKnowledgeSource();
            default -> throw new IllegalStateException("sjw.kb.mode는 file|noop 중 하나여야 함: " + mode);
        };
        log.info("KB 소스: mode={} version={}", mode, kb.version());
        return kb;
    }
}
