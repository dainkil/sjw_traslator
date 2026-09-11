package dev.sjw.common.cache;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.common.quality.QualityGate;
import dev.sjw.common.quality.QualityGrade;
import dev.sjw.common.translate.TranslationDtos.EntityDto;
import dev.sjw.common.translate.TranslationDtos.Meta;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import dev.sjw.common.translate.TranslationDtos.UncertainSpan;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * 2단 캐시 (§5.2, ADR-009).
 *
 * <ul>
 *   <li><b>L1 (원문 완전 일치)</b> — 히트는 LLM 호출 0회 + NER 추론 0회다. 키가 파이프라인 버전과
 *       원문 해시만으로 만들어지므로 전처리 <i>전에</i> 판정할 수 있다.
 *   <li><b>L2 (템플릿 구조 일치)</b> — 히트는 LLM 호출 0회지만 <b>NER·링킹은 수행한다</b>.
 *       슬롯화에 링크 확정 PER이 필요하므로 전처리 <i>뒤에</i>만 판정할 수 있고, 꽂아 넣을 인명은
 *       캐시가 아니라 지금 이 문장의 링킹 결과여야 한다.
 * </ul>
 *
 * <p><b>적재 정책이 품질 방어선이다</b> (ADR-009): L1은 게이트 통과분(VERIFIED/DEGRADED, 등급 보존),
 * L2는 <b>VERIFIED + 모든 슬롯의 한글명 전체형이 번역문에 출현</b>할 때만. 게이트는 이름부 일치
 * ("문회")도 반영으로 인정하지만 템플릿화는 인명 구간을 특정해야 하므로 전체형만 허용한다
 * — 히트율을 조금 버리고 안전을 산다.
 *
 * <p>L2는 <b>기본 off, 명시 opt-in</b>이다. §5.4 비열등 임계를 통과해야 켠다 (M3-S5).
 */
@Component
public class TranslationCache {

    private static final Logger log = LoggerFactory.getLogger(TranslationCache.class);

    /**
     * 캐시에 들어가는 JSON은 <b>저장 포맷</b>이다 — 앱의 Jackson 설정이 바뀌면 예전 엔트리를
     * 못 읽는 일이 생기므로 주입받지 않고 여기서 고정한다 (JobProcessor의 JSON 상수와 같은 이유).
     */
    private static final ObjectMapper JSON = new ObjectMapper();

    private final StringRedisTemplate redis;
    private final PipelineVersions versions;
    private final TemplateSlotter slotter;
    private final QualityGate qualityGate;
    private final MeterRegistry meters;
    private final boolean l1Enabled;
    private final Duration l1Ttl;
    private final boolean l2Enabled;
    private final Duration l2Ttl;

    public TranslationCache(StringRedisTemplate redis, PipelineVersions versions,
                            TemplateSlotter slotter, QualityGate qualityGate,
                            MeterRegistry meters,
                            @Value("${sjw.cache.l1.enabled:true}") boolean l1Enabled,
                            @Value("${sjw.cache.l1.ttl-days:30}") long l1TtlDays,
                            @Value("${sjw.cache.l2.enabled:false}") boolean l2Enabled,
                            @Value("${sjw.cache.l2.ttl-days:30}") long l2TtlDays) {
        this.redis = redis;
        this.versions = versions;
        this.slotter = slotter;
        this.qualityGate = qualityGate;
        this.meters = meters;
        this.l1Enabled = l1Enabled;
        this.l1Ttl = Duration.ofDays(l1TtlDays);
        this.l2Enabled = l2Enabled;
        this.l2Ttl = Duration.ofDays(l2TtlDays);
    }

    public boolean enabled() {
        return l1Enabled;
    }

    public boolean l2Enabled() {
        return l2Enabled;
    }

    // ── L1: 원문 완전 일치 ────────────────────────────────────────────────

    /**
     * 히트면 캐시된 결과. 미스·비활성·버전 미확보는 전부 empty다.
     *
     * <p>비활성일 때는 미스로 세지 않는다 — 기능을 꺼둔 것과 캐시가 못 맞춘 것은 다르다.
     * 히트율의 분모를 오염시키면 S4의 on/off 비교가 무의미해진다.
     */
    public Optional<CachedTranslation> lookupL1(String sourceText) {
        if (!l1Enabled) {
            return Optional.empty();
        }
        Optional<PipelineVersion> version = versions.current();
        if (version.isEmpty()) {
            miss(CacheLevel.L1_EXACT);
            return Optional.empty();
        }
        String key = CacheKeys.l1(version.get(), sourceText);
        String raw = redis.opsForValue().get(key);
        if (raw == null) {
            miss(CacheLevel.L1_EXACT);
            return Optional.empty();
        }
        try {
            CachedTranslation hit = JSON.readValue(raw, CachedTranslation.class);
            hit(CacheLevel.L1_EXACT);
            return Optional.of(hit);
        } catch (Exception e) {
            // 옛 포맷 잔존 — 되살릴 수 없는 값을 남겨두면 계속 같은 비용을 문다
            log.warn("L1 캐시 역직렬화 실패 — 키 폐기 {}: {}", key, e.getMessage());
            redis.delete(key);
            miss(CacheLevel.L1_EXACT);
            return Optional.empty();
        }
    }

    /** 게이트 통과분만 적재 (ADR-009). REJECTED·빈 번역문·버전 미확보는 조용히 건너뛴다. */
    public void storeL1(String sourceText, TranslationResponse resp, QualityGrade grade) {
        if (!l1Enabled || grade == QualityGrade.REJECTED) {
            return;
        }
        if (resp == null || resp.translatedText() == null || resp.translatedText().isBlank()) {
            return;
        }
        Optional<PipelineVersion> version = versions.current();
        if (version.isEmpty()) {
            return;
        }
        CachedTranslation value = new CachedTranslation(
                resp.translatedText(), resp.entities(), resp.uncertainSpans(),
                resp.meta() == null ? null : resp.meta().model(),
                grade.name(), Instant.now().toString());
        try {
            redis.opsForValue().set(CacheKeys.l1(version.get(), sourceText),
                    JSON.writeValueAsString(value), l1Ttl);
        } catch (Exception e) {
            // 캐시 적재 실패로 번역을 실패시키지 않는다 — 캐시는 비용 최적화지 정확성 경로가 아니다
            log.warn("L1 캐시 적재 실패 (무시): {}", e.getMessage());
        }
    }

    /**
     * 캐시된 값을 응답으로 되살린다. 토큰은 비운다 — 쓰지 않은 토큰을 계상하면 비용 SLI가
     * 오염된다. 모델은 이 번역을 실제로 만든 모델을 그대로 보존한다.
     */
    public TranslationResponse toResponse(CachedTranslation hit, long lookupMs) {
        Map<String, Long> latency = new LinkedHashMap<>();
        latency.put("cache", lookupMs);
        latency.put("total", lookupMs);
        PipelineVersion v = versions.current().orElse(null);
        return new TranslationResponse(
                hit.translatedText(), hit.entities(), hit.uncertainSpans(),
                new Meta(hit.producedModel(),
                        v == null ? null : v.kb(),
                        v == null ? null : v.prompt(),
                        null, null, latency, CacheLevel.L1_EXACT.name()));
    }

    // ── L2: 템플릿 구조 일치 ──────────────────────────────────────────────

    /**
     * L2 조회 결과.
     *
     * <p>{@code templateHash}는 <b>히트 여부와 L2 on/off에 무관하게</b> 채워진다 — S4의 히트율
     * 시뮬레이션은 "L2를 껐던 기간의 job들이 서로 틀을 공유했는가"를 사후에 계산해야 하고,
     * 그 입력이 job 행에 남은 이 값이다. 기능을 켜야만 기록되는 값으로는 그 계산이 성립하지 않는다.
     *
     * <p>{@code translatedText}가 null이면 <b>L2 대상이지만 미스</b>(또는 조회를 하지 않은 상태)다.
     */
    public record L2Lookup(String templateHash, String translatedText, String producedModel) {
        public boolean hit() {
            return translatedText != null;
        }
    }

    /**
     * 슬롯화 → 템플릿 조회 → 재주입까지 끝낸 결과를 돌려준다.
     *
     * <p>{@code Optional.empty()}는 <b>L2 대상이 아님</b>이다 (링크 확정 PER 0명 — 슬롯이 없으면
     * 구조 일치를 말할 수 없다). 이 경우는 미스로 세지 않는다: L2가 커버한다고 주장한 적 없는
     * 문장을 분모에 넣으면 히트율이 실제보다 낮게 보인다. 대상/전체 비율은 job 행의
     * {@code template_hash} NULL 여부로 따로 나온다.
     *
     * <p>재주입 취소(구조 불일치·게이트 불합격)는 <b>미스로 센다</b> — 조회했고 서빙하지 못했으므로.
     */
    public Optional<L2Lookup> lookupL2(String sourceText, List<EntityDto> entities) {
        Optional<PipelineVersion> version = versions.current();
        if (version.isEmpty()) {
            return Optional.empty();
        }
        Optional<TemplateSlotter.SlottedSource> slotted = slotter.slotSource(sourceText, entities);
        if (slotted.isEmpty()) {
            return Optional.empty();
        }
        String templateHash = slotter.templateHash(slotted.get());
        if (!l2Enabled) {
            // 꺼져 있어도 해시는 돌려준다 (S4 시뮬레이션 입력). 미스로는 세지 않는다.
            return Optional.of(new L2Lookup(templateHash, null, null));
        }

        String key = CacheKeys.l2(version.get(), templateHash);
        String raw = redis.opsForValue().get(key);
        if (raw == null) {
            miss(CacheLevel.L2_TEMPLATE);
            return Optional.of(new L2Lookup(templateHash, null, null));
        }

        CachedTemplate cached;
        try {
            cached = JSON.readValue(raw, CachedTemplate.class);
        } catch (Exception e) {
            log.warn("L2 캐시 역직렬화 실패 — 키 폐기 {}: {}", key, e.getMessage());
            redis.delete(key);
            abort("deserialize");
            miss(CacheLevel.L2_TEMPLATE);
            return Optional.of(new L2Lookup(templateHash, null, null));
        }

        // 재주입: 마커 누락·잔존은 히트 취소 → 전체 파이프라인 fallback (M3 수용 기준)
        Optional<String> reinjected = slotter.reinject(cached.translationTemplate(), slotted.get());
        if (reinjected.isEmpty()) {
            log.warn("L2 재주입 취소 (마커 누락 또는 잔존 — 적재 시 슬롯 {}개, 이번 문장 슬롯 {}개) "
                    + "— 전체 파이프라인으로 진행", cached.slotCount(), slotted.get().slots().size());
            abort("structure_mismatch");
            miss(CacheLevel.L2_TEMPLATE);
            return Optional.of(new L2Lookup(templateHash, null, null));
        }

        // 재주입 결과의 런타임 검증 (ADR-009 배경 3). 확정 인명이 실제로 들어갔는지 결정론 검사 —
        // LLM 추가 호출 0회다. 재주입은 구조상 이 검사를 통과해야 정상이므로, 불합격은 버그 신호다.
        var probe = new TranslationResponse(reinjected.get(), entities, List.of(), null);
        if (qualityGate.grade(probe).grade() == QualityGrade.REJECTED) {
            log.warn("L2 재주입 결과가 게이트 불합격 — 히트 취소 (재주입 로직 회귀 신호)");
            abort("gate_rejected");
            miss(CacheLevel.L2_TEMPLATE);
            return Optional.of(new L2Lookup(templateHash, null, null));
        }

        hit(CacheLevel.L2_TEMPLATE);
        return Optional.of(new L2Lookup(templateHash, reinjected.get(), cached.producedModel()));
    }

    /**
     * 번역문을 템플릿화해 적재한다. <b>VERIFIED에 한정</b>한다 (ADR-009).
     *
     * <p>DEGRADED를 배제하는 이유: DEGRADED는 KB가 특정하지 못한 인물이 문장에 있다는 뜻이고,
     * 그 인물은 슬롯이 아니라 <b>문면 그대로 템플릿에 박힌다</b>. 구조가 같은 다른 문장에 그 틀을
     * 쓰면 남의 이름이 그대로 따라 나간다.
     */
    public void storeL2(String sourceText, List<EntityDto> entities,
                        TranslationResponse resp, QualityGrade grade) {
        if (!l2Enabled || grade != QualityGrade.VERIFIED) {
            return;
        }
        if (resp == null || resp.translatedText() == null || resp.translatedText().isBlank()) {
            return;
        }
        Optional<PipelineVersion> version = versions.current();
        if (version.isEmpty()) {
            return;
        }
        Optional<TemplateSlotter.SlottedSource> slotted = slotter.slotSource(sourceText, entities);
        if (slotted.isEmpty()) {
            return;
        }
        // 전체형 출현 요건은 여기서 강제된다 — 하나라도 없으면 empty (보수적 적재)
        Optional<String> template =
                slotter.templateizeTranslation(resp.translatedText(), slotted.get());
        if (template.isEmpty()) {
            return;
        }
        CachedTemplate value = new CachedTemplate(template.get(),
                resp.meta() == null ? null : resp.meta().model(),
                slotted.get().slots().size(), Instant.now().toString());
        try {
            redis.opsForValue().set(CacheKeys.l2(version.get(), slotter.templateHash(slotted.get())),
                    JSON.writeValueAsString(value), l2Ttl);
        } catch (Exception e) {
            log.warn("L2 캐시 적재 실패 (무시): {}", e.getMessage());
        }
    }

    /**
     * L2 히트를 응답으로 만든다.
     *
     * <p>엔티티·불확실 구간은 <b>캐시가 아니라 이번 문장의 링킹 결과</b>다 (L2의 정의).
     * 전처리 지연(ner/link/prompt)은 실제로 발생했으므로 그대로 보존하고 cache 단계만 더한다 —
     * L1처럼 total을 조회 시간으로 덮으면 "NER은 돌았다"는 사실이 지표에서 사라진다.
     */
    public TranslationResponse toResponseL2(L2Lookup hit, List<EntityDto> entities,
                                            List<UncertainSpan> uncertainSpans,
                                            Map<String, Long> baseLatencyMs, long lookupMs) {
        Map<String, Long> latency = new LinkedHashMap<>(
                baseLatencyMs == null ? Map.of() : baseLatencyMs);
        latency.put("cache", lookupMs);
        latency.put("total", latency.values().stream().mapToLong(Long::longValue).sum());
        PipelineVersion v = versions.current().orElse(null);
        return new TranslationResponse(
                hit.translatedText(), entities, uncertainSpans,
                new Meta(hit.producedModel(),
                        v == null ? null : v.kb(),
                        v == null ? null : v.prompt(),
                        null, null, latency, CacheLevel.L2_TEMPLATE.name()));
    }

    // ── 계측 ────────────────────────────────────────────────────────────

    private void hit(CacheLevel level) {
        meters.counter("translation.cache.hit", "level", level.metricLabel()).increment();
    }

    private void miss(CacheLevel level) {
        meters.counter("translation.cache.miss", "level", level.metricLabel()).increment();
    }

    /** 엔트리는 있었는데 서빙하지 못한 경우의 사유별 시계열 (§9.1, M3-S3 추가). */
    private void abort(String reason) {
        meters.counter("translation.cache.reinject.abort", "reason", reason).increment();
    }
}
