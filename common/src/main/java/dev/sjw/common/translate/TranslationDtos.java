package dev.sjw.common.translate;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;

public final class TranslationDtos {

    private TranslationDtos() {}

    public record TranslateRequest(
            @NotBlank @Size(max = 2000) String text,
            Integer year  // 문서 연도(서기). 없으면 시간 필터 비활성
    ) {}

    /** LLM Structured Output 대상 (BeanOutputConverter). */
    public record LlmOutput(
            String translatedText,
            List<UncertainSpan> uncertainSpans
    ) {}

    public record UncertainSpan(String text, String reason) {}

    public record EntityDto(
            String surface, String type, String kbId, String resolvedName,
            double confidence, String linkStage, boolean ambiguous
    ) {}

    public record Meta(
            String model, String kbVersion, String promptVersion,
            Integer tokensIn, Integer tokensOut,
            Map<String, Long> latencyMs
    ) {}

    public record TranslationResponse(
            String translatedText,
            List<EntityDto> entities,
            List<UncertainSpan> uncertainSpans,
            Meta meta
    ) {}
}
