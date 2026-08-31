package dev.sjw.worker.rate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import dev.sjw.common.queue.QueueKeys;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 토큰 버킷 + AIMD 실동작 검증 (M2-S5).
 *
 * <p>실제 Redis에 붙는다 — Lua 원자성이 검증 대상의 절반이라 인메모리 대역으로는 의미가 없다.
 * Redis가 없으면 {@code assumeTrue}로 건너뛴다:
 * {@code docker compose -f deploy/docker-compose.yml up -d}
 *
 * <p>여기서 429는 모의값이다. 실제 provider 429로 rate가 내려갔다 올라오는 것은
 * {@code deploy/demo-rate-control.sh}가 실호출로 증명한다.
 */
class AdaptiveRateLimiterTest {

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

        boolean alive = false;
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
        usedModels.forEach(m -> redis.delete(QueueKeys.rateBucket(m)));
        usedModels.clear();
    }

    @Test
    void 버킷_용량을_비운_뒤에는_설정된_rate로_페이싱된다() {
        // 60 RPM, 버스트 1초치 → 용량 1개, 보충 1개/초
        var limiter = limiter(props(60, 2, 120, 1, 0.5, 5, 1, 10_000));
        String model = model();

        assertTrue(limiter.tryAcquire(model).granted(), "가득 찬 버킷의 첫 permit은 즉시 통과");

        var denied = limiter.tryAcquire(model);
        assertFalse(denied.granted(), "용량을 비웠으므로 즉시 재요청은 거절");
        assertTrue(denied.waitMs() > 500 && denied.waitMs() <= 1000,
                "60 RPM이면 다음 토큰까지 약 1초를 안내해야 함: " + denied.waitMs());

        long waited = limiter.acquire(model); // 블로킹 — 이 대기가 워커의 페이싱이다
        assertTrue(waited >= 700 && waited < 3000, "약 1초 대기 후 통과해야 함: " + waited);
    }

    @Test
    void 여러_워커가_동시에_요청해도_버킷_용량을_넘지_않는다() throws Exception {
        // 6 RPM, 버스트 100초치 → 용량 10개, 보충은 10초에 1개(테스트 창 안에서는 사실상 0)
        var cfg = props(6, 2, 60, 100, 0.5, 5, 1, 10_000);
        var workerA = limiter(cfg);
        var workerB = limiter(cfg); // 다른 인스턴스 = 다른 워커 프로세스를 흉내
        String model = model();

        int threads = 40;
        var pool = Executors.newFixedThreadPool(threads);
        var start = new CountDownLatch(1);
        var done = new CountDownLatch(threads);
        var granted = new AtomicInteger();
        for (int i = 0; i < threads; i++) {
            AdaptiveRateLimiter limiter = (i % 2 == 0) ? workerA : workerB;
            pool.execute(() -> {
                try {
                    start.await();
                    if (limiter.tryAcquire(model).granted()) {
                        granted.incrementAndGet();
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    done.countDown();
                }
            });
        }
        start.countDown();
        assertTrue(done.await(10, TimeUnit.SECONDS), "동시 요청이 끝나야 함");
        shutdown(pool);

        assertEquals(10, granted.get(),
                "용량 10을 넘거나 모자라면 read-modify-write가 원자적이지 않다는 뜻");
    }

    @Test
    void _429_피드백은_rate를_절반으로_내리고_하한에서_멈춘다() {
        var limiter = limiter(props(20, 2, 60, 10, 0.5, 5, 1, 10_000));
        String model = model();
        limiter.tryAcquire(model); // 버킷 생성

        limiter.onRateLimited(model, null);
        assertEquals(10, limiter.snapshot(model).rpm());
        limiter.onRateLimited(model, null);
        assertEquals(5, limiter.snapshot(model).rpm());
        limiter.onRateLimited(model, null);
        assertEquals(2, limiter.snapshot(model).rpm());
        limiter.onRateLimited(model, null);
        assertEquals(2, limiter.snapshot(model).rpm(), "하한 밑으로는 내려가지 않는다");
    }

    @Test
    void 연속_성공이_쌓이면_rate가_한_단계씩_오른다() {
        var limiter = limiter(props(10, 2, 12, 10, 0.5, 3, 1, 10_000));
        String model = model();
        limiter.tryAcquire(model);

        limiter.onSuccess(model);
        limiter.onSuccess(model);
        assertEquals(10, limiter.snapshot(model).rpm(), "아직 임계(3회) 미달");

        limiter.onSuccess(model);
        assertEquals(11, limiter.snapshot(model).rpm(), "연속 3회 → +1 RPM");
        assertEquals(0, limiter.snapshot(model).streak(), "증가 후 연속 카운터는 리셋");

        for (int i = 0; i < 6; i++) {
            limiter.onSuccess(model);
        }
        assertEquals(12, limiter.snapshot(model).rpm(), "상한(12)에서 멈춘다");
    }

    @Test
    void _429가_알려준_재시도_지연_동안은_permit이_나오지_않는다() {
        var limiter = limiter(props(120, 2, 120, 1, 0.5, 5, 1, 10_000));
        String model = model();
        limiter.tryAcquire(model);

        limiter.onRateLimited(model, Duration.ofSeconds(2)); // provider 힌트 2초

        var denied = limiter.tryAcquire(model);
        assertFalse(denied.granted(), "쿨다운 동안은 토큰이 있어도 permit을 주지 않는다");
        assertTrue(denied.waitMs() > 1000 && denied.waitMs() <= 2000,
                "남은 쿨다운을 안내해야 함: " + denied.waitMs());
        assertEquals(60, denied.rpm(), "동시에 rate도 절반으로 내려가 있어야 함");

        long waited = limiter.acquire(model); // 쿨다운 종료 후 토큰 1개가 찰 때까지
        assertTrue(waited >= 1900, "최소한 쿨다운만큼은 기다려야 함: " + waited);
    }

    @Test
    void 대기가_상한을_넘으면_호출하지_않고_예외로_되돌린다() {
        // 2 RPM = 토큰 1개에 30초. 상한 300ms이면 기다릴 수 없다.
        var limiter = limiter(props(2, 2, 60, 1, 0.5, 5, 1, 300));
        String model = model();
        assertTrue(limiter.tryAcquire(model).granted());

        long t0 = System.nanoTime();
        assertThrows(RateLimitWaitTimeoutException.class, () -> limiter.acquire(model));
        long elapsed = (System.nanoTime() - t0) / 1_000_000;
        assertTrue(elapsed < 3000, "상한 근처에서 포기해야 함: " + elapsed);
    }

    // --- 헬퍼 ---

    private AdaptiveRateLimiter limiter(RateLimitProperties cfg) {
        return new AdaptiveRateLimiter(redis, cfg, new SimpleMeterRegistry());
    }

    private static RateLimitProperties props(int initialRpm, int minRpm, int maxRpm, int burstSeconds,
                                             double decreaseFactor, int successesToIncrease,
                                             int increaseStep, long maxWaitMs) {
        return new RateLimitProperties(initialRpm, minRpm, maxRpm, burstSeconds,
                decreaseFactor, successesToIncrease, increaseStep, maxWaitMs);
    }

    /** 테스트마다 새 버킷 키 — 잔여 상태가 다음 테스트로 새지 않게. */
    private String model() {
        String m = "test-" + UUID.randomUUID();
        usedModels.add(m);
        return m;
    }

    private static void shutdown(ExecutorService pool) throws InterruptedException {
        pool.shutdown();
        if (!pool.awaitTermination(5, TimeUnit.SECONDS)) {
            pool.shutdownNow();
        }
    }
}
