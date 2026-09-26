package dev.sjw.api.translation;

import dev.sjw.api.tenant.TenantGuard;
import dev.sjw.common.cache.CacheLevel;
import dev.sjw.common.cache.CachedTranslation;
import dev.sjw.common.cache.TranslationCache;
import dev.sjw.common.llm.Translator;
import dev.sjw.common.llm.TranslatorFactory;
import dev.sjw.common.quality.QualityGate;
import dev.sjw.common.translate.TranslationDtos.TranslateRequest;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationService;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.validation.Valid;
import java.util.Optional;
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
    private final TranslationCache cache;
    private final QualityGate qualityGate;
    private final MeterRegistry meters;

    public TranslationController(TranslationService service, TranslatorFactory translatorFactory,
                                 TenantGuard tenantGuard, TranslationCache cache,
                                 QualityGate qualityGate, MeterRegistry meters) {
        this.service = service;
        this.translatorFactory = translatorFactory;
        this.tenantGuard = tenantGuard;
        this.cache = cache;
        this.qualityGate = qualityGate;
        this.meters = meters;
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

    /** worker와 같은 계측 이름·태그 — 대시보드가 경로를 가리지 않고 합산한다 (§5.0 1-4). */
    private void recordCall(String tenantId, Integer tokensIn, Integer tokensOut) {
        meters.counter("tenant.calls", "tenant", tenantId).increment();
        if (tokensIn != null) {
            meters.counter("llm.tokens", "direction", "in").increment(tokensIn);
        }
        if (tokensOut != null) {
            meters.counter("llm.tokens", "direction", "out").increment(tokensOut);
        }
    }

    /**
     * M1 동기 엔드포인트 — 단계별 지연 실측용으로 유지.
     * 비동기 경로(202 + jobId)는 JobController 참조 (ADR-001).
     *
     * <p>캐시 히트는 <b>테넌트 일일 상한을 소모하지 않는다</b> — 무료 티어의 예산 단위는 원화가
     * 아니라 LLM 호출 수인데(§8.2), 히트는 호출을 0회 만든다. 그래서 조회가 charge보다 앞이다.
     * L2는 전처리(NER·링킹) 뒤에만 판정할 수 있으므로 <b>charge를 LLM 호출 직전까지 내렸다</b>
     * (M3-S3). 상한을 이미 넘긴 테넌트는 그 앞의 {@code ensureWithinCap}이 돌려보낸다.
     */
    @PostMapping("/sync")
    public TranslationResponse translateSync(
            @Valid @RequestBody TranslateRequest req,
            @RequestHeader(value = "X-Api-Key", required = false) String apiKey,
            @RequestHeader(value = "X-Llm-Key", required = false) String llmKey) {
        var tenant = tenantGuard.resolve(apiKey);
        long start = System.nanoTime();
        Optional<CachedTranslation> hit = cache.lookupL1(req.text());
        if (hit.isPresent()) {
            return cache.toResponse(hit.get(), (System.nanoTime() - start) / 1_000_000);
        }

        tenantGuard.requireByok(llmKey);       // 공개 모드: 캐시 미스는 BYOK만 (§15.3)
        tenantGuard.ensureWithinCap(tenant);   // 과금은 LLM 직전 — 문 앞에서만 막는다
        var prep = service.prepare(req.text(), req.year());

        // L2는 전처리 뒤에만 판정할 수 있다 (슬롯화에 링크 확정 PER이 필요하다).
        long l2Start = System.nanoTime();
        var l2 = cache.lookupL2(req.text(), prep.entities());
        if (l2.isPresent() && l2.get().hit()) {
            return cache.toResponseL2(l2.get(), prep.entities(), prep.kbMisses(),
                    prep.latencyMs(), (System.nanoTime() - l2Start) / 1_000_000);
        }

        // 예산 단위는 LLM 호출 수다 (§8.2) — 과금은 실제로 호출하는 자리에서 한다.
        tenantGuard.charge(tenant, 1);
        Translator byok = pickTranslator(llmKey);
        TranslationResponse resp = byok == null
                ? service.translate(prep)
                : service.translate(prep, byok);

        // 적재 전 품질 게이트 (ADR-009: 게이트 통과분만). LLM 추가 호출 0회의 결정론 검사다.
        QualityGate.Verdict verdict = qualityGate.grade(resp);
        recordCall(tenant.id(), resp.meta().tokensIn(), resp.meta().tokensOut());
        meters.counter("translation.quality.grade", "grade", verdict.grade().name()).increment();
        if (byok == null && !translatorFactory.isFake(resp.meta().model())) {
            // BYOK 결과는 공용 캐시에 적재하지 않는다 — 요청자가 자기 키로 산 번역을
            // 다른 테넌트가 공짜로 받아가는 모양이 된다. 조회는 위에서 이미 허용했다.
            // fake provider 결과도 적재하지 않는다 — 캐시 키에 모델이 없어 실 요청이 가짜를 받게 된다.
            cache.storeL1(req.text(), resp, verdict.grade());
            cache.storeL2(req.text(), resp.entities(), resp, verdict.grade());
        }
        return resp;
    }

    /**
     * 단건 SSE 스트리밍 (D7): entities 이벤트 1회 → token 이벤트 다수 → done 이벤트.
     * 데모 체감 지연용 경로라 worker의 rate 버킷 밖이다 — 테넌트 일일 상한(TenantGuard)이 이 자리를 막는다.
     *
     * <p>스트림 경로는 Structured Output을 쓰지 않아 채점할 스키마 결과가 없다 — 조회만 하고
     * 적재하지 않는다.
     */
    @PostMapping(value = "/stream", produces = org.springframework.http.MediaType.TEXT_EVENT_STREAM_VALUE)
    public org.springframework.web.servlet.mvc.method.annotation.SseEmitter translateStream(
            @Valid @RequestBody TranslateRequest req,
            @RequestHeader(value = "X-Api-Key", required = false) String apiKey,
            @RequestHeader(value = "X-Llm-Key", required = false) String llmKey) {
        var tenant = tenantGuard.resolve(apiKey);
        var emitter = new org.springframework.web.servlet.mvc.method.annotation.SseEmitter(120_000L);
        long start = System.nanoTime();

        Optional<CachedTranslation> hit = cache.lookupL1(req.text());
        if (hit.isPresent()) {
            var cachedResp = cache.toResponse(hit.get(), (System.nanoTime() - start) / 1_000_000);
            try {
                emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                        .name("entities").data(cachedResp.entities()));
                emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                        .name("token").data(cachedResp.translatedText()));
                emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                        .name("done").data(java.util.Map.of(
                                "totalMs", (System.nanoTime() - start) / 1_000_000,
                                "cacheHit", CacheLevel.L1_EXACT.name())));
                emitter.complete();
            } catch (java.io.IOException e) {
                emitter.completeWithError(e);
            }
            return emitter;
        }

        tenantGuard.requireByok(llmKey);
        tenantGuard.ensureWithinCap(tenant);
        var prep = service.prepare(req.text(), req.year());
        try {
            emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                    .name("entities").data(prep.entities()));
        } catch (java.io.IOException e) {
            emitter.completeWithError(e);
            return emitter;
        }

        // L2 히트는 스트리밍할 토큰이 없다 — 이미 완성된 문장이므로 token 1회로 내보낸다.
        long l2Start = System.nanoTime();
        var l2 = cache.lookupL2(req.text(), prep.entities());
        if (l2.isPresent() && l2.get().hit()) {
            try {
                emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                        .name("token").data(l2.get().translatedText()));
                emitter.send(org.springframework.web.servlet.mvc.method.annotation.SseEmitter.event()
                        .name("done").data(java.util.Map.of(
                                "totalMs", (System.nanoTime() - start) / 1_000_000,
                                "cacheHit", CacheLevel.L2_TEMPLATE.name())));
                emitter.complete();
            } catch (java.io.IOException e) {
                emitter.completeWithError(e);
            }
            return emitter;
        }

        tenantGuard.charge(tenant, 1);
        recordCall(tenant.id(), null, null);   // 스트림은 usage를 돌려받지 않는다 — 호출 수만
        Translator byok = pickTranslator(llmKey);
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
