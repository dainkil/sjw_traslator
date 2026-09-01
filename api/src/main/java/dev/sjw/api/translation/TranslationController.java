package dev.sjw.api.translation;

import dev.sjw.api.tenant.TenantGuard;
import dev.sjw.common.llm.Translator;
import dev.sjw.common.llm.TranslatorFactory;
import dev.sjw.common.translate.TranslationDtos.TranslateRequest;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/translations")
public class TranslationController {

    private final TranslationService service;
    private final TranslatorFactory translatorFactory;
    private final TenantGuard tenantGuard;

    public TranslationController(TranslationService service, TranslatorFactory translatorFactory,
                                 TenantGuard tenantGuard) {
        this.service = service;
        this.translatorFactory = translatorFactory;
        this.tenantGuard = tenantGuard;
    }

    /**
     * BYOK (D10/ADR-020): X-Llm-Key가 오면 그 키로 요청 단위 클라이언트를 만든다.
     * 키는 이 메서드 스코프에서만 살고 저장·로깅되지 않는다. 없으면 운영자 키(활성 Translator).
     */
    private Translator pickTranslator(String llmKey) {
        return (llmKey == null || llmKey.isBlank())
                ? null
                : translatorFactory.forModelWithKey(service.model(), llmKey);
    }

    /**
     * M1 동기 엔드포인트 — 단계별 지연 실측용으로 유지.
     * 비동기 경로(202 + jobId)는 JobController 참조 (ADR-001).
     */
    @PostMapping("/sync")
    public TranslationResponse translateSync(
            @Valid @RequestBody TranslateRequest req,
            @RequestHeader(value = "X-Api-Key", required = false) String apiKey,
            @RequestHeader(value = "X-Llm-Key", required = false) String llmKey) {
        var tenant = tenantGuard.resolve(apiKey);
        tenantGuard.charge(tenant, 1);
        Translator byok = pickTranslator(llmKey);
        return byok == null
                ? service.translate(req.text(), req.year())
                : service.translate(service.prepare(req.text(), req.year()), byok);
    }

    /**
     * 단건 SSE 스트리밍 (D7): entities 이벤트 1회 → token 이벤트 다수 → done 이벤트.
     * 데모 체감 지연용 경로라 worker의 rate 버킷 밖이다 — 테넌트 일일 상한(TenantGuard)이 이 자리를 막는다.
     */
    @PostMapping(value = "/stream", produces = org.springframework.http.MediaType.TEXT_EVENT_STREAM_VALUE)
    public org.springframework.web.servlet.mvc.method.annotation.SseEmitter translateStream(
            @Valid @RequestBody TranslateRequest req,
            @RequestHeader(value = "X-Api-Key", required = false) String apiKey,
            @RequestHeader(value = "X-Llm-Key", required = false) String llmKey) {
        var tenant = tenantGuard.resolve(apiKey);
        tenantGuard.charge(tenant, 1);
        Translator byok = pickTranslator(llmKey);

        var emitter = new org.springframework.web.servlet.mvc.method.annotation.SseEmitter(120_000L);
        long start = System.nanoTime();
        var prep = service.prepare(req.text(), req.year());
        try {
            emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                    .name("entities").data(prep.entities()));
        } catch (java.io.IOException e) {
            emitter.completeWithError(e);
            return emitter;
        }
        var flux = byok == null ? service.translateStream(prep) : service.translateStream(prep, byok);
        flux.subscribe(
                chunk -> {
                    try {
                        emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                                .name("token").data(chunk));
                    } catch (java.io.IOException e) {
                        throw new RuntimeException(e);
                    }
                },
                emitter::completeWithError,
                () -> {
                    try {
                        emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                                .name("done")
                                .data(java.util.Map.of("totalMs", (System.nanoTime() - start) / 1_000_000)));
                        emitter.complete();
                    } catch (java.io.IOException e) {
                        emitter.completeWithError(e);
                    }
                });
        return emitter;
    }
}
