package dev.sjw.common.cache;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.sjw.common.quality.QualityGrade;
import dev.sjw.common.translate.TranslationDtos.Meta;
import dev.sjw.common.translate.TranslationDtos.TranslationResponse;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * L1(원문 완전 일치) 캐시 (§5.2, ADR-009). 히트는 LLM 호출 0회 + NER 추론 0회다 —
 * 키가 파이프라인 버전과 원문 해시만으로 만들어지므로 전처리 전에 판정할 수 있다.
 *
 * <p><b>적재 정책이 품질 방어선이다</b>: 게이트 통과분(VERIFIED/DEGRADED)만 적재하고 등급을
 * 값에 보존한다. REJECTED가 캐시에 박히면 그 오역이 계속 서빙된다.
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
    private final MeterRegistry meters;
    private final boolean enabled;
    private final Duration ttl;

    public TranslationCache(StringRedisTemplate redis, PipelineVersions versions,
                            MeterRegistry meters,
                            @Value("${sjw.cache.l1.enabled:true}") boolean enabled,
                            @Value("${sjw.cache.l1.ttl-days:30}") long ttlDays) {
        this.redis = redis;
        this.versions = versions;
        this.meters = meters;
        this.enabled = enabled;
        this.ttl = Duration.ofDays(ttlDays);
    }

    public boolean enabled() {
        return enabled;
    }

    /**
     * 히트면 캐시된 결과. 미스·비활성·버전 미확보는 전부 empty다.
     *
     * <p>비활성일 때는 미스로 세지 않는다 — 기능을 꺼둔 것과 캐시가 못 맞춘 것은 다르다.
     * 히트율의 분모를 오염시키면 S4의 on/off 비교가 무의미해진다.
     */
    public Optional<CachedTranslation> lookupL1(String sourceText) {
        if (!enabled) {
            return Optional.empty();
        }
        Optional<PipelineVersion> version = versions.current();
        if (version.isEmpty()) {
            miss();
            return Optional.empty();
        }
        String key = CacheKeys.l1(version.get(), sourceText);
        String raw = redis.opsForValue().get(key);
        if (raw == null) {
            miss();
            return Optional.empty();
        }
        try {
            CachedTranslation hit = JSON.readValue(raw, CachedTranslation.class);
            meters.counter("translation.cache.hit", "level", CacheLevel.L1_EXACT.metricLabel())
                    .increment();
            return Optional.of(hit);
        } catch (Exception e) {
            // 옛 포맷 잔존 — 되살릴 수 없는 값을 남겨두면 계속 같은 비용을 문다
            log.warn("L1 캐시 역직렬화 실패 — 키 폐기 {}: {}", key, e.getMessage());
            redis.delete(key);
            miss();
            return Optional.empty();
        }
    }

    /** 게이트 통과분만 적재 (ADR-009). REJECTED·빈 번역문·버전 미확보는 조용히 건너뛴다. */
    public void storeL1(String sourceText, TranslationResponse resp, QualityGrade grade) {
        if (!enabled || grade == QualityGrade.REJECTED) {
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
                    JSON.writeValueAsString(value), ttl);
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

    private void miss() {
        meters.counter("translation.cache.miss", "level", CacheLevel.L1_EXACT.metricLabel())
                .increment();
    }
}
