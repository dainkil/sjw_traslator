package dev.sjw.worker.rate;

import dev.sjw.common.llm.ModelRegistry;
import dev.sjw.common.queue.QueueKeys;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Component;

/**
 * 모델별 공유 토큰 버킷 + AIMD 자가 조정 (§6 "고정 상수 금지", 계획서 §8.3 {@code rate:bucket:*}).
 *
 * <p><b>왜 Redis인가.</b> 버킷은 워커 프로세스가 아니라 "모델의 provider quota"에 속한 상태다.
 * in-process 리미터(Resilience4j RateLimiter, Bucket4j 로컬 모드)는 워커가 N개면 각자 quota를
 * 전부 쓰려 들어 합계가 provider 한도의 N배가 된다. 상태를 Redis에 두고 read-modify-write를
 * Lua로 원자화한다 (ADR-017).
 *
 * <p><b>왜 AIMD인가.</b> provider의 실제 RPM은 문서값과 다르고 모델·시간대별로 변한다(실측:
 * docs/troubleshooting.md §2·§3). 그래서 "정확한 상수"를 찾는 대신 429를 피드백 신호로 삼아
 * 절반으로 줄이고(즉시 회피), 연속 성공으로 1씩 올린다(조심스러운 재탐색). 감소는 크고 증가는
 * 작은 비대칭이 재진입 발진을 막는다.
 *
 * <p><b>실측 한도가 있으면 그것을 쓴다 (M4-S1).</b> 버킷은 모델별인데 탐색 경계는 전역 상수
 * 하나였다 — 그래서 실측 RPM 15인 모델도 20에서 출발해 기동마다 429를 한 번 사서 배웠고,
 * 상한 60은 실측의 4배였다. 레지스트리에 모델의 {@code rpm}이 실측돼 있으면 그 값을
 * <b>시작점과 상한</b>으로 쓰고, 없는 모델만 전역 기본값으로 탐색한다. AIMD는 그대로 남는다 —
 * 실측값도 provider가 바꿀 수 있고, 그때 스스로 내려오는 것이 이 설계의 요점이다.
 */
@Component
public class AdaptiveRateLimiter {

    /** permit 획득 시도 1회의 결과. {@code waitMs}는 거절 시 "이만큼 뒤에 다시 오라"는 값. */
    public record Decision(boolean granted, long waitMs, int rpm, double tokens) {}

    /** 운영·데모용 버킷 상태 스냅샷. {@code cooldownUntilMs}는 redis 서버 클럭 기준 epoch ms. */
    public record Snapshot(int rpm, double tokens, long cooldownUntilMs, int streak) {}

    private static final Logger log = LoggerFactory.getLogger(AdaptiveRateLimiter.class);

    /** 대기를 이 단위로 쪼갠다 — 종료 시 인터럽트에 1초 안에 반응하기 위해. */
    private static final long SLEEP_SLICE_MS = 1000;

    private static final String OP_SUCCESS = "success";
    private static final String OP_THROTTLE = "throttle";

    private final StringRedisTemplate redis;
    private final RateLimitProperties cfg;
    private final ModelRegistry models;
    private final MeterRegistry meters;
    private final RedisScript<List> acquireScript = load("rate/acquire.lua");
    private final RedisScript<List> feedbackScript = load("rate/feedback.lua");

    private final Map<String, AtomicInteger> rpmGauges = new ConcurrentHashMap<>();
    private final Map<String, Timer> waitTimers = new ConcurrentHashMap<>();

    public AdaptiveRateLimiter(StringRedisTemplate redis, RateLimitProperties cfg,
                               ModelRegistry models, MeterRegistry meters) {
        this.redis = redis;
        this.cfg = cfg;
        this.models = models;
        this.meters = meters;
    }

    /**
     * 이 버킷의 탐색 경계 — 실측값이 있으면 그것이 시작점이자 상한이다.
     *
     * <p>버킷 스코프는 {@code {tenant}:{model}}이므로 첫 {@code :} 뒤가 모델 id다
     * ({@link QueueKeys#rateScope}). 등록되지 않은 모델이나 미실측 모델은 전역 기본값으로 탐색한다.
     */
    private int[] bounds(String bucket) {
        int sep = bucket.indexOf(':');
        String model = sep < 0 ? bucket : bucket.substring(sep + 1);
        Integer rpm = models.measuredRpm(model).orElse(null);
        if (rpm == null) {
            return new int[] {cfg.initialRpm(), cfg.maxRpm()};
        }
        // 실측 한도가 하한보다 낮을 수도 있다 — 그 경우 하한을 존중한다(0 RPM은 진행 불가)
        return new int[] {Math.max(cfg.minRpm(), rpm), Math.max(cfg.minRpm(), rpm)};
    }

    @SuppressWarnings("rawtypes")
    private static RedisScript<List> load(String classpath) {
        DefaultRedisScript<List> script = new DefaultRedisScript<>();
        script.setLocation(new ClassPathResource(classpath));
        script.setResultType(List.class);
        return script;
    }

    /** 논블로킹 획득 시도. 거절되면 {@code waitMs} 뒤에 재시도하면 된다. */
    public Decision tryAcquire(String bucket) {
        int[] b = bounds(bucket);
        List<Long> r = exec(acquireScript, bucket,
                String.valueOf(b[0]),
                String.valueOf(cfg.minRpm()),
                String.valueOf(b[1]),
                String.valueOf(cfg.burstSeconds()));
        Decision d = new Decision(r.get(0) == 1L, r.get(1), r.get(2).intValue(), r.get(3) / 100.0);
        rpmGauge(bucket).set(d.rpm());
        return d;
    }

    /**
     * permit을 얻을 때까지 블로킹한다. 이 대기가 곧 워커의 페이싱이다.
     *
     * @return 실제 대기한 밀리초
     * @throws RateLimitWaitTimeoutException 대기가 {@code maxWaitMs}를 넘거나 인터럽트된 경우
     */
    public long acquire(String bucket) {
        long start = System.nanoTime();
        Decision d = tryAcquire(bucket);
        while (!d.granted()) {
            long elapsed = elapsedMs(start);
            if (elapsed >= cfg.maxWaitMs()) {
                throw new RateLimitWaitTimeoutException(
                        "permit 대기 상한 초과: bucket=%s, %dms 대기, 현재 %d RPM"
                                .formatted(bucket, elapsed, d.rpm()));
            }
            long slice = Math.max(20, Math.min(Math.min(d.waitMs(), SLEEP_SLICE_MS),
                    cfg.maxWaitMs() - elapsed));
            sleep(slice, bucket);
            d = tryAcquire(bucket);
        }
        long waited = elapsedMs(start);
        waitTimer(bucket).record(waited, TimeUnit.MILLISECONDS);
        if (waited > 0) {
            log.debug("permit 대기 {}ms (bucket={}, {} RPM)", waited, bucket, d.rpm());
        }
        return waited;
    }

    /** 성공 피드백 — 연속 N회면 rate를 한 단계 올린다 (AIMD의 AI). */
    public void onSuccess(String bucket) {
        List<Long> r = feedback(bucket, OP_SUCCESS, 0L);
        int rpm = r.get(0).intValue();
        rpmGauge(bucket).set(rpm);
    }

    /**
     * 429(RATE_LIMITED) 피드백 — rate를 곱셈 감소시키고 쿨다운을 건다 (AIMD의 MD).
     *
     * @param providerHint 응답이 알려준 재시도 지연. null이면 새 rate의 1틱을 쿨다운으로 쓴다.
     */
    public void onRateLimited(String bucket, Duration providerHint) {
        long hintMs = providerHint == null ? 0L : Math.max(0L, providerHint.toMillis());
        int before = rpmGauge(bucket).get();
        List<Long> r = feedback(bucket, OP_THROTTLE, hintMs);
        int rpm = r.get(0).intValue();
        long cooldown = r.get(1);
        rpmGauge(bucket).set(rpm);
        meters.counter("llm.rate_limit.429", "bucket", bucket).increment();
        log.warn("429 피드백: bucket={} rate {} → {} RPM, 쿨다운 {}ms{}",
                bucket, before, rpm, cooldown, providerHint == null ? "" : " (provider 힌트)");
    }

    /** 버킷 원상태 조회 (테스트·데모·운영 확인용). 버킷이 없으면 설정 초기값을 반영해 돌려준다. */
    public Snapshot snapshot(String bucket) {
        Map<Object, Object> h = redis.opsForHash().entries(QueueKeys.rateBucket(bucket));
        return new Snapshot(
                (int) num(h.get("rpm"), bounds(bucket)[0]),
                num(h.get("tokens"), 0),
                (long) num(h.get("cooldown_until"), 0),
                (int) num(h.get("streak"), 0));
    }

    private List<Long> feedback(String bucket, String op, long hintMs) {
        int[] b = bounds(bucket);
        return exec(feedbackScript, bucket,
                op,
                String.valueOf(b[0]),
                String.valueOf(cfg.minRpm()),
                String.valueOf(b[1]),
                String.valueOf(cfg.decreaseFactor()),
                String.valueOf(cfg.successesToIncrease()),
                String.valueOf(cfg.increaseStep()),
                String.valueOf(hintMs));
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private List<Long> exec(RedisScript<List> script, String bucket, String... args) {
        List<Long> r = (List<Long>) redis.execute(script,
                List.of(QueueKeys.rateBucket(bucket)), (Object[]) args);
        if (r == null) {
            throw new IllegalStateException("rate 스크립트가 결과를 반환하지 않음: bucket=" + bucket);
        }
        return r;
    }

    private AtomicInteger rpmGauge(String bucket) {
        return rpmGauges.computeIfAbsent(bucket, m -> {
            AtomicInteger holder = new AtomicInteger(bounds(m)[0]);
            Gauge.builder("llm.rate.rpm", holder, AtomicInteger::doubleValue)
                    .description("적응형 토큰 버킷의 현재 RPM (429 피드백으로 자가 조정)")
                    .tag("bucket", m)
                    .register(meters);
            return holder;
        });
    }

    private Timer waitTimer(String bucket) {
        return waitTimers.computeIfAbsent(bucket, m -> Timer.builder("llm.rate.wait")
                .description("LLM 호출 전 permit 대기 시간")
                .tag("bucket", m)
                .register(meters));
    }

    private static double num(Object v, double fallback) {
        return v == null ? fallback : Double.parseDouble(String.valueOf(v));
    }

    private static long elapsedMs(long startNanos) {
        return (System.nanoTime() - startNanos) / 1_000_000;
    }

    private static void sleep(long ms, String bucket) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new RateLimitWaitTimeoutException("permit 대기 중 인터럽트: bucket=" + bucket);
        }
    }
}
