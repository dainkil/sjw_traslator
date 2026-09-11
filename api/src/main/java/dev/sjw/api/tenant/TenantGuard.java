package dev.sjw.api.tenant;

import dev.sjw.common.queue.QueueKeys;
import dev.sjw.common.tenant.Tenant;
import dev.sjw.common.tenant.TenantRepository;
import java.time.Duration;
import java.time.LocalDate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * 테넌트 식별(X-Api-Key) + 일일 사용량 상한 (D10, 계획서 §13 "타인의 quota 소진" 방어).
 * BYOK LLM 키(X-Llm-Key)는 여기를 지나지 않는다 — 식별·과금과 키는 별개 축이다.
 */
@Component
public class TenantGuard {

    public static class UnknownApiKeyException extends RuntimeException {}

    public static class DailyLimitExceededException extends RuntimeException {
        public final int limit;

        public DailyLimitExceededException(int limit) {
            this.limit = limit;
        }
    }

    private final TenantRepository tenants;
    private final StringRedisTemplate redis;

    public TenantGuard(TenantRepository tenants, StringRedisTemplate redis) {
        this.tenants = tenants;
        this.redis = redis;
    }

    /** 헤더 없음 → default 테넌트 (개발·단독 운영). 미등록 키 → 401. */
    public Tenant resolve(String apiKeyHeader) {
        if (apiKeyHeader == null || apiKeyHeader.isBlank()) {
            return tenants.defaultTenant();
        }
        return tenants.findByApiKey(apiKeyHeader).orElseThrow(UnknownApiKeyException::new);
    }

    /**
     * 소모 없이 상한 초과 여부만 확인한다 (M3-S3).
     *
     * <p>과금(charge)은 LLM 호출 직전으로 내려갔다 — 예산 단위가 LLM 호출 수이므로 캐시 히트와
     * 전처리 단계 실패는 상한을 소모해선 안 된다(§8.2, ADR-009). 그러면 이미 초과한 테넌트가
     * 전처리(NER 추론)를 공짜로 쓰게 되므로 그 앞에 이 빠른 거절을 둔다. 경합으로 1~2건 새는 것은
     * 허용한다: 정확한 방어선은 charge의 INCR이고 이쪽은 문 앞에서 돌려보내는 용도다.
     */
    public void ensureWithinCap(Tenant tenant) {
        String used = redis.opsForValue()
                .get(QueueKeys.budgetDaily(tenant.id(), LocalDate.now().toString()));
        if (used != null && Long.parseLong(used) >= tenant.dailyCallLimit()) {
            throw new DailyLimitExceededException(tenant.dailyCallLimit());
        }
    }

    /**
     * 일일 카운터에 호출 수를 선과금한다 (수용 시점 — 배치는 job 수만큼).
     * 초과분은 남겨둔다: 오늘은 이미 초과 상태라는 사실 자체가 정확한 기록이다.
     */
    public void charge(Tenant tenant, int calls) {
        String key = QueueKeys.budgetDaily(tenant.id(), LocalDate.now().toString());
        Long used = redis.opsForValue().increment(key, calls);
        redis.expire(key, Duration.ofDays(2));
        if (used != null && used > tenant.dailyCallLimit()) {
            throw new DailyLimitExceededException(tenant.dailyCallLimit());
        }
    }
}
