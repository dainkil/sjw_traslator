package dev.sjw.common.ner;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** NER 어댑터 선택 — 설정만으로 교체한다 (M2.5 수용 기준 2). */
@Configuration
public class NerConfig {

    private static final Logger log = LoggerFactory.getLogger(NerConfig.class);

    @Bean
    public EntityRecognizer entityRecognizer(
            @Value("${sjw.ner.mode:http}") String mode,
            @Value("${sjw.ner.url}") String url) {
        EntityRecognizer recognizer = switch (mode) {
            case "http" -> new HttpOnnxRecognizer(url);
            case "rule" -> new RulePatternRecognizer();
            default -> throw new IllegalStateException(
                    "sjw.ner.mode는 http|rule 중 하나여야 함: " + mode);
        };
        log.info("NER 어댑터: {} (mode={})", recognizer.id(), mode);
        return recognizer;
    }
}
