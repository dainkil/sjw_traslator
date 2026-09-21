package dev.sjw.common.llm;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Locale;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 가짜 LLM provider의 <b>프로세스 상태</b> — quota 창·난수·지연은 모델별 Translator 인스턴스가 아니라
 * 여기 산다. 승격·BYOK가 호출마다 {@link TranslatorFactory#forModel}로 새 Translator를 만들기 때문에,
 * 상태가 인스턴스에 있으면 quota가 호출마다 리셋된다.
 *
 * 429 본문은 실측 로그의 형태를 따른다 (docs/troubleshooting.md §2, M3-S5 quotaValue):
 * 워커의 {@code FailureClassifier}가 "PerDay"/"PerMinute"로 QUOTA_DAILY/RATE_LIMITED를 가르고
 * {@code RetryAfterHint}가 "retry in Ns"를 읽는다 — 가짜가 그 계약을 지켜야 워커 코드가
 * 실 provider와 같은 경로를 탄다. 그것이 이 클래스의 존재 이유다.
 *
 * <p>한계: quota 창은 프로세스 단위다. api와 worker가 각자 세므로 실 provider(프로젝트 단위)와 다르다.
 * 워커 단일 인스턴스(D11)라 배치 경로에선 문제가 없고, 동기 경로와 합산은 안 된다.
 */
public class FakeProvider {

    /** provider가 던지는 장애. 메시지 문자열이 분류 계약이므로 타입은 부차적이다. */
    public static class ProviderError extends RuntimeException {
        public ProviderError(String message) {
            super(message);
        }
    }

    private final FakeLlmProperties cfg;
    private final Clock clock;
    private final Random random; // seed가 있으면 공유 Random(동기화), 없으면 ThreadLocalRandom
    private final Map<String, Window> windows = new ConcurrentHashMap<>();

    public FakeProvider(FakeLlmProperties cfg) {
        this(cfg, Clock.systemUTC());
    }

    public FakeProvider(FakeLlmProperties cfg, Clock clock) {
        this.cfg = cfg;
        this.clock = clock;
        this.random = cfg.seed() == null ? null : new Random(cfg.seed());
    }

    public FakeLlmProperties config() {
        return cfg;
    }

    public Translator translator(String modelId) {
        return new FakeTranslator(modelId, this);
    }

    /**
     * 호출 1건의 입장 절차: quota(429) → 지연 → 503 주입. 실 provider처럼 429는 지연 없이 즉시,
     * 503은 시간을 쓴 뒤에 온다. quota는 성공·503 무관하게 요청 도착 시 계정된다.
     */
    void admit(String modelId) {
        window(modelId).admit(Instant.now(clock), modelId);
        sleep(latencyMs());
        if (chance(cfg.errorRate())) {
            throw new ProviderError("503 UNAVAILABLE. The model is overloaded. Please try again later. "
                    + "[fake provider, model: " + modelId + "]");
        }
    }

    /** 스트림용: 지연 없이 quota·503만 판정한다 (지연은 Reactor 타이머로 비차단 처리). */
    void admitStream(String modelId) {
        window(modelId).admit(Instant.now(clock), modelId);
        if (chance(cfg.errorRate())) {
            throw new ProviderError("503 UNAVAILABLE. The model is overloaded. Please try again later. "
                    + "[fake provider, model: " + modelId + "]");
        }
    }

    long latencyMs() {
        int jitter = cfg.jitterMs() == 0 ? 0 : nextInt(cfg.jitterMs() + 1);
        return cfg.latencyMs() + jitter;
    }

    boolean dropName() {
        return chance(cfg.dropNameRate());
    }

    /** 모델별 계정 상태 (테스트·데모 관측용). */
    public int callsInLastMinute(String modelId) {
        return window(modelId).minuteCount(Instant.now(clock));
    }

    public long callsToday(String modelId) {
        return window(modelId).dayCount(Instant.now(clock));
    }

    private Window window(String modelId) {
        return windows.computeIfAbsent(modelId, k -> new Window(cfg.rpm(), cfg.rpd()));
    }

    private boolean chance(double p) {
        return p > 0 && nextDouble() < p;
    }

    private double nextDouble() {
        if (random == null) {
            return ThreadLocalRandom.current().nextDouble();
        }
        synchronized (random) {
            return random.nextDouble();
        }
    }

    private int nextInt(int bound) {
        if (random == null) {
            return ThreadLocalRandom.current().nextInt(bound);
        }
        synchronized (random) {
            return random.nextInt(bound);
        }
    }

    private static void sleep(long ms) {
        if (ms <= 0) {
            return;
        }
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ProviderError("fake provider 지연 중 인터럽트");
        }
    }

    /** 모델 하나의 분당 슬라이딩 창 + 일일 카운터. */
    private static final class Window {
        private final Integer rpm;
        private final Integer rpd;
        private final Deque<Instant> lastMinute = new ArrayDeque<>();
        private LocalDate day;
        private long dayCount;

        Window(Integer rpm, Integer rpd) {
            this.rpm = rpm;
            this.rpd = rpd;
        }

        synchronized void admit(Instant now, String modelId) {
            rollDay(now);
            if (rpd != null && dayCount >= rpd) {
                long secondsToReset = Math.max(1, day.plusDays(1).atStartOfDay(ZoneOffset.UTC).toEpochSecond()
                        - now.getEpochSecond());
                throw new ProviderError(quota429("GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                        rpd, modelId, secondsToReset));
            }
            evict(now);
            if (rpm != null && lastMinute.size() >= rpm) {
                double retryIn = Math.max(0.1,
                        (lastMinute.peekFirst().toEpochMilli() + 60_000 - now.toEpochMilli()) / 1000.0);
                throw new ProviderError(quota429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                        rpm, modelId, retryIn));
            }
            lastMinute.addLast(now);
            dayCount++;
        }

        synchronized int minuteCount(Instant now) {
            evict(now);
            return lastMinute.size();
        }

        synchronized long dayCount(Instant now) {
            rollDay(now);
            return dayCount;
        }

        private void rollDay(Instant now) {
            LocalDate today = LocalDate.ofInstant(now, ZoneOffset.UTC);
            if (!today.equals(day)) {
                day = today;
                dayCount = 0;
            }
        }

        private void evict(Instant now) {
            Instant cutoff = now.minusSeconds(60);
            while (!lastMinute.isEmpty() && !lastMinute.peekFirst().isAfter(cutoff)) {
                lastMinute.pollFirst();
            }
        }

        private static String quota429(String quotaId, int quotaValue, String modelId, double retryInSeconds) {
            return String.format(Locale.ROOT,
                    "429 RESOURCE_EXHAUSTED. You exceeded your current quota. "
                            + "quota_metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                            + "quotaId: %s, quotaValue: %d, model: %s. Please retry in %.1fs. [fake provider]",
                    quotaId, quotaValue, modelId, retryInSeconds);
        }
    }
}
