package dev.sjw.common.llm;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

/** 가짜 provider의 quota 창·장애 주입·재현성. 시계를 손으로 돌린다 — 60초를 기다리는 테스트는 테스트가 아니다. */
class FakeProviderTest {

    /** 테스트용 가변 시계. */
    static final class MutableClock extends Clock {
        Instant now = Instant.parse("2026-09-21T10:00:00Z");
        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
        void advance(Duration d) { now = now.plus(d); }
    }

    private static FakeLlmProperties cfg(Integer rpm, Integer rpd, double errorRate, double dropRate, Long seed) {
        return new FakeLlmProperties(0, 0, rpm, rpd, errorRate, dropRate, seed);
    }

    @Test
    void 분당_창을_넘으면_429_PerMinute_그리고_60초_뒤_회복() {
        var clock = new MutableClock();
        var p = new FakeProvider(cfg(2, null, 0, 0, null), clock);
        p.admit("fake-flash-lite");
        p.admit("fake-flash-lite");
        var e = assertThrows(FakeProvider.ProviderError.class, () -> p.admit("fake-flash-lite"));
        assertTrue(e.getMessage().contains("429"), e.getMessage());
        assertTrue(e.getMessage().contains("PerMinutePerProjectPerModel"), e.getMessage());
        assertTrue(e.getMessage().matches("(?s).*retry in [0-9.]+s.*"), e.getMessage());   // RetryAfterHint 계약
        assertEquals(2, p.callsInLastMinute("fake-flash-lite"));
        clock.advance(Duration.ofSeconds(61));
        assertDoesNotThrow(() -> p.admit("fake-flash-lite"));
        assertEquals(1, p.callsInLastMinute("fake-flash-lite"));
    }

    @Test
    void 일일_한도를_넘으면_429_PerDay_그리고_UTC_자정에_리셋() {
        var clock = new MutableClock();
        var p = new FakeProvider(cfg(null, 2, 0, 0, null), clock);
        p.admit("m");
        p.admit("m");
        var e = assertThrows(FakeProvider.ProviderError.class, () -> p.admit("m"));
        assertTrue(e.getMessage().contains("PerDayPerProjectPerModel"), e.getMessage());
        assertEquals(2, p.callsToday("m"));
        clock.advance(Duration.ofHours(15));   // 10:00 → 다음 날 01:00 UTC
        assertDoesNotThrow(() -> p.admit("m"));
        assertEquals(1, p.callsToday("m"));
    }

    @Test
    void quota_창은_모델별이다() {
        var p = new FakeProvider(cfg(1, null, 0, 0, null), new MutableClock());
        p.admit("a");
        assertThrows(FakeProvider.ProviderError.class, () -> p.admit("a"));
        assertDoesNotThrow(() -> p.admit("b"));   // 다른 모델은 자기 창
    }

    @Test
    void errorRate_1이면_항상_503() {
        var p = new FakeProvider(cfg(null, null, 1.0, 0, null), new MutableClock());
        var e = assertThrows(FakeProvider.ProviderError.class, () -> p.admit("m"));
        assertTrue(e.getMessage().contains("503"), e.getMessage());
        assertTrue(e.getMessage().toLowerCase().contains("unavailable"), e.getMessage());
    }

    @Test
    void 시드가_같으면_장애_순서가_재현된다() {
        var a = new FakeProvider(cfg(null, null, 0, 0.5, 7L), new MutableClock());
        var b = new FakeProvider(cfg(null, null, 0, 0.5, 7L), new MutableClock());
        List<Boolean> sa = new ArrayList<>(), sb = new ArrayList<>();
        for (int i = 0; i < 30; i++) {
            sa.add(a.dropName());
            sb.add(b.dropName());
        }
        assertEquals(sa, sb);
        assertTrue(sa.contains(true) && sa.contains(false), "0.5면 양쪽 다 나와야 한다: " + sa);
    }

    @Test
    void 손잡이_검증은_기동_시점에_실패한다() {
        assertThrows(IllegalArgumentException.class, () -> new FakeLlmProperties(-1, 0, null, null, 0.0, 0.0, null));
        assertThrows(IllegalArgumentException.class, () -> new FakeLlmProperties(0, 0, 0, null, 0.0, 0.0, null));
        assertThrows(IllegalArgumentException.class, () -> new FakeLlmProperties(0, 0, null, null, 1.5, 0.0, null));
        var d = FakeLlmProperties.defaults();
        assertEquals(100, d.latencyMs());
        assertEquals(0.0, d.errorRate());
    }
}
