package dev.sjw.api.translation;

import dev.sjw.common.translate.TranslationDtos.TranslateRequest;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationService;
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
     * M1 동기 엔드포인트 — 단계별 지연 실측용으로 유지.
     * 비동기 경로(202 + jobId)는 M2에서 추가된다 (ADR-001).
     */
    @PostMapping("/sync")
    public TranslationResponse translateSync(@Valid @RequestBody TranslateRequest req) {
        return service.translate(req.text(), req.year());
    }
}
