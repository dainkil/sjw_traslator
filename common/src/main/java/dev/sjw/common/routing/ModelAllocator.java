package dev.sjw.common.routing;

import dev.sjw.common.llm.ModelRegistry;
import dev.sjw.common.llm.ModelSpec;
import dev.sjw.common.queue.QueueKeys;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.time.LocalDate;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * 난이도 티어를 실제 모델로 바꾸는 <b>예산 인식 배정기</b> (ADR-010).
 *
 * <p>왜 별도 컴포넌트인가: 무료 티어에서 모델 간 차이는 단가(전부 0)가 아니라 <b>quota</b>이고,
 * 상위 모델의 quota는 희소 자원이다 — 실측 RPD는 flash-lite 500 / 3.5-flash 20이다. 난이도 판정을
 * 모델에 1:1로 묶으면 상위 티어 수요가 quota를 8배 초과해 배치가 거기서 정체된다(M4-S1 실측:
 * 라우팅을 그렇게 켜면 완역이 124일 → 926일로 늘어난다). 그래서 "무엇이 어려운가"(TierRouter)와
 * "그걸 어디로 보낼 수 있는가"(여기)를 분리한다.
 *
 * <p><b>초과 배정을 구조적으로 막는다.</b> 상위 모델로 보내기 전에 Redis에서 그 모델의 일일
 * quota를 원자적으로 예약하고(INCR 후 한도 비교), 자리가 없으면 기본 모델로 강등한다. 예약 카운터는
 * <b>테넌트가 아니라 모델</b> 단위다 — provider quota가 프로젝트×모델 단위이기 때문이다.
 *
 * <p>이미 구현된 품질 기반 상향(REJECTED → 상위 티어, §5.4)도 이 문을 지나야 한다. 실측 REJECTED율
 * 4.36%는 상위 모델 quota의 135배여서, 문이 없으면 상향이 quota를 즉시 태우고 이후의 모든 상향이
 * 실패한다 — 정작 필요한 문장에 quota가 남아 있지 않게 된다.
 */
@Component
public class ModelAllocator {

    private static final Logger log = LoggerFactory.getLogger(ModelAllocator.class);

    /** 예약 결과. {@code downgraded}면 quota가 없어 기본 모델로 내려온 것이다. */
    public record Allocation(String modelId, Tier tier, boolean downgraded, String reason) {}

    private final ModelRegistry registry;
    private final StringRedisTemplate redis;
    private final MeterRegistry meters;
    private final String upperModel;
    private final boolean enabled;

    public ModelAllocator(ModelRegistry registry, StringRedisTemplate redis, MeterRegistry meters,
                          @org.springframework.beans.factory.annotation.Value(
                                  "${sjw.routing.upper-model:gemini-3.5-flash}") String upperModel,
                          @org.springframework.beans.factory.annotation.Value(
                                  "${sjw.routing.enabled:false}") boolean enabled) {
        this.registry = registry;
        this.redis = redis;
        this.meters = meters;
        this.upperModel = upperModel;
        this.enabled = enabled;
    }

    public boolean enabled() {
        return enabled;
    }

    /**
     * 티어에 맞는 모델을 배정한다. T2만 상위 모델을 노리고, 그것도 quota가 남아 있을 때만이다.
     *
     * @param baseModel 기본(활성) 모델 id — T0·T1과 강등의 목적지
     */
    public Allocation allocate(Tier tier, String baseModel) {
        if (!enabled || tier != Tier.T2 || upperModel == null || upperModel.equals(baseModel)) {
            return new Allocation(baseModel, tier, false, "기본 모델");
        }
        Optional<String> reserved = reserve(upperModel);
        if (reserved.isEmpty()) {
            meters.counter("translation.tier.downgrade", "reason", "quota_exhausted",
                    "model", upperModel).increment();
            return new Allocation(baseModel, tier, true,
                    "상위 모델 " + upperModel + " 일일 quota 소진 — 기본 모델로 강등");
        }
        return new Allocation(upperModel, tier, false, "T2 → 상위 모델 (quota 예약 " + reserved.get() + ")");
    }

    /**
     * 품질 기반 상향(§5.4)의 문. 게이트가 REJECTED를 냈다고 무조건 상위 모델을 쓰면 안 된다 —
     * quota가 먼저 소진되면 뒤따르는 진짜 필요한 승격이 전부 실패한다.
     *
     * @return 쓸 수 있는 상위 모델 id, 자리가 없으면 empty
     */
    public Optional<String> reserveForPromotion(String baseModel) {
        if (upperModel == null || upperModel.equals(baseModel)) {
            return Optional.empty();
        }
        Optional<String> r = reserve(upperModel);
        if (r.isEmpty()) {
            meters.counter("translation.quality.upgrade.skipped", "reason", "quota_exhausted",
                    "model", upperModel).increment();
        }
        return r.map(used -> upperModel);
    }

    /**
     * provider 일일 quota를 원자적으로 예약한다. 실측 rpd가 없는 모델은 제한하지 않는다 —
     * 측정되지 않은 값을 상수로 가정하는 것이 이 프로젝트가 피하는 일이다(원칙 4).
     *
     * @return 예약 후 사용량 문자열, 한도 초과면 empty
     */
    private Optional<String> reserve(String model) {
        ModelSpec spec;
        try {
            spec = registry.require(model);
        } catch (IllegalStateException notRegistered) {
            log.warn("레지스트리에 없는 상위 모델 {} — 배정하지 않는다", model);
            return Optional.empty();
        }
        if (spec.rpd() == null) {
            return Optional.of("무제한(rpd 미실측)");
        }
        String key = QueueKeys.providerQuotaDaily(model, LocalDate.now().toString());
        Long used = redis.opsForValue().increment(key);
        redis.expire(key, Duration.ofDays(2));
        if (used == null) {
            return Optional.of("카운터 없음");
        }
        if (used > spec.rpd()) {
            // 초과분은 되돌린다 — 예약에 실패한 호출이 카운터를 밀어올리면
            // 다음 요청들이 실제 소진량보다 이른 시점에 막힌다
            redis.opsForValue().decrement(key);
            return Optional.empty();
        }
        return Optional.of(used + "/" + spec.rpd());
    }
}
