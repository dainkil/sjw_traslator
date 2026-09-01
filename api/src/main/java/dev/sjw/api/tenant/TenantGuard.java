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
