package dev.sjw.api.translation;

import dev.sjw.api.translation.TranslationDtos.TranslateRequest;
import dev.sjw.api.translation.TranslationDtos.TranslationResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/translations")
public class TranslationController {

    private final TranslationService service;

    public TranslationController(TranslationService service) {
        this.service = service;
    }

    /**
     * M1 임시 동기 엔드포인트 — 단계별 지연 실측용.
     * M2에서 202 + jobId 비동기(큐 발행)로 전환되며 이 경로는 제거된다 (ADR-001).
     */
    @PostMapping("/sync")
    public TranslationResponse translateSync(@Valid @RequestBody TranslateRequest req) {
        return service.translate(req.text(), req.year());
    }
}
