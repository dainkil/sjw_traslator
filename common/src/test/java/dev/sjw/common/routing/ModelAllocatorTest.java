package dev.sjw.common.routing;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import dev.sjw.common.llm.LlmProperties;
import dev.sjw.common.llm.ModelRegistry;
import dev.sjw.common.llm.ModelSpec;
import dev.sjw.common.queue.QueueKeys;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 예산 인식 배정 검증 (M4-S1, ADR-010).
 *
 * <p>실제 Redis에 붙는다 — 검증 대상이 "원자적 예약으로 quota 초과를 막는가"이고, 그 원자성이
 * 저장소의 성질이다. Redis가 없으면 건너뛴다:
 * {@code docker compose -f deploy/docker-compose.yml up -d}
 */
class ModelAllocatorTest {

    private static final String BASE = "base-model";

    private static LettuceConnectionFactory factory;
    private static StringRedisTemplate redis;

    private final List<String> usedModels = new ArrayList<>();

    @BeforeAll
    static void connect() {
        factory = new LettuceConnectionFactory(new RedisStandaloneConfiguration("localhost", 6379));
        factory.afterPropertiesSet();
        factory.start();
        redis = new StringRedisTemplate(factory);
        redis.afterPropertiesSet();

        boolean alive;
        RedisConnection conn = null;
        try {
            conn = factory.getConnection();
            alive = "PONG".equalsIgnoreCase(conn.ping());
        } catch (Exception e) {
            alive = false;
        } finally {
            if (conn != null) {
                try {
                    conn.close();
                } catch (Exception ignored) {
                    // 검증 대상이 아님
                }
            }
        }
        assumeTrue(alive, "로컬 Redis(:6379)가 없어 건너뜀 — docker compose -f deploy/docker-compose.yml up -d");
    }

    @AfterAll
    static void disconnect() {
        if (factory != null) {
            factory.destroy();
        }
    }

    @AfterEach
    void cleanup() {
        usedModels.forEach(m ->
                redis.delete(QueueKeys.providerQuotaDaily(m, LocalDate.now().toString())));
        usedModels.clear();
    }

    @Test
    void T2는_상위_모델로_가고_quota가_소진되면_강등된다() {
        String upper = upperModel(3);       // 하루 3회만 허용되는 상위 모델
        var allocator = allocator(upper, 3, new SimpleMeterRegistry(), true);

        for (int i = 1; i <= 3; i++) {
            var a = allocator.allocate(Tier.T2, BASE);
            assertEquals(upper, a.modelId(), i + "번째 배정은 quota 안에 있다");
            assertFalse(a.downgraded());
        }
        // 4번째는 자리가 없다 — 상위 모델 대신 기본 모델로 내려온다
        var over = allocator.allocate(Tier.T2, BASE);
        assertEquals(BASE, over.modelId(), "quota를 넘겨 배정하면 429가 확정이다");
        assertTrue(over.downgraded());
        assertTrue(over.reason().contains("quota 소진"));
    }

    @Test
    void 강등이_계측된다() {
        String upper = upperModel(1);
        MeterRegistry meters = new SimpleMeterRegistry();
        var allocator = allocator(upper, 1, meters, true);

        allocator.allocate(Tier.T2, BASE);      // quota 소모
        allocator.allocate(Tier.T2, BASE);      // 강등

        assertEquals(1.0, meters.get("translation.tier.downgrade")
                .tag("reason", "quota_exhausted").tag("model", upper).counter().count());
    }

    @Test
    void 실패한_예약은_카운터를_밀어올리지_않는다() {
        String upper = upperModel(2);
        var allocator = allocator(upper, 2, new SimpleMeterRegistry(), true);
        allocator.allocate(Tier.T2, BASE);
        allocator.allocate(Tier.T2, BASE);      // 여기서 2/2 소진

        for (int i = 0; i < 5; i++) {
            allocator.allocate(Tier.T2, BASE);  // 전부 강등
        }

        // 초과 시도가 카운터를 5 더 올려버리면, 내일 리셋 전까지 실제 소진량을 알 수 없게 된다
        String key = QueueKeys.providerQuotaDaily(upper, LocalDate.now().toString());
        assertEquals("2", redis.opsForValue().get(key));
    }

    @Test
    void T0과_T1은_quota를_소모하지_않는다() {
        String upper = upperModel(1);
        var allocator = allocator(upper, 1, new SimpleMeterRegistry(), true);

        assertEquals(BASE, allocator.allocate(Tier.T0, BASE).modelId());
        assertEquals(BASE, allocator.allocate(Tier.T1, BASE).modelId());

        // 상위 모델 자리는 그대로 남아 있어야 한다 — T2가 쓸 몫이다
        assertEquals(upper, allocator.allocate(Tier.T2, BASE).modelId());
    }

    @Test
    void 라우팅이_꺼져_있으면_티어와_무관하게_기본_모델이다() {
        String upper = upperModel(5);
        var allocator = allocator(upper, 5, new SimpleMeterRegistry(), false);

        var a = allocator.allocate(Tier.T2, BASE);

        assertEquals(BASE, a.modelId());
        assertFalse(a.downgraded(), "꺼진 것은 강등이 아니다 — 지표를 오염시키면 안 된다");
        assertEquals(null, redis.opsForValue()
                .get(QueueKeys.providerQuotaDaily(upper, LocalDate.now().toString())));
    }

    @Test
    void 품질_기반_상향도_같은_문을_지난다() {
        // 실측 REJECTED율 4.36%는 상위 모델 quota의 135배다 — 문이 없으면 상향이 quota를 태우고
        // 이후의 모든 상향이 실패한다. 라우팅 on/off와 무관하게 문은 닫혀 있어야 한다.
        String upper = upperModel(2);
        MeterRegistry meters = new SimpleMeterRegistry();
        var allocator = allocator(upper, 2, meters, false);

        assertEquals(upper, allocator.reserveForPromotion(BASE).orElseThrow());
        assertEquals(upper, allocator.reserveForPromotion(BASE).orElseThrow());
        assertTrue(allocator.reserveForPromotion(BASE).isEmpty(), "quota를 넘겨 승격하면 안 된다");

        assertEquals(1.0, meters.get("translation.quality.upgrade.skipped")
                .tag("reason", "quota_exhausted").tag("model", upper).counter().count());
    }

    @Test
    void rpd가_미실측인_모델은_제한하지_않는다() {
        // 측정되지 않은 값을 상수로 가정하는 것이 이 프로젝트가 피하는 일이다 (원칙 4)
        String upper = upperModel(null);
        var allocator = allocator(upper, null, new SimpleMeterRegistry(), true);

        for (int i = 0; i < 10; i++) {
            assertEquals(upper, allocator.allocate(Tier.T2, BASE).modelId());
        }
    }

    @Test
    void 레지스트리에_없는_상위_모델은_배정되지_않는다() {
        var allocator = allocator("등록되지-않은-모델", 5, new SimpleMeterRegistry(), true);

        var a = allocator.allocate(Tier.T2, BASE);

        assertEquals(BASE, a.modelId());
        assertTrue(a.downgraded());
    }

    // --- 조립 도구 ---

    private String upperModel(Integer rpd) {
        String m = "upper-" + UUID.randomUUID();
        usedModels.add(m);
        return m;
    }

    private ModelAllocator allocator(String upper, Integer upperRpd, MeterRegistry meters,
                                     boolean enabled) {
        var specs = new ArrayList<ModelSpec>();
        specs.add(new ModelSpec(BASE, "google-genai", "T0", 500, 15,
                BigDecimal.ZERO, BigDecimal.ZERO));
        if (upper.startsWith("upper-")) {
            specs.add(new ModelSpec(upper, "google-genai", "T1", upperRpd, null,
                    BigDecimal.ZERO, BigDecimal.ZERO));
        }
        var registry = new ModelRegistry(new LlmProperties(BASE, BigDecimal.ONE, specs));
        return new ModelAllocator(registry, redis, meters, upper, enabled);
    }
}
