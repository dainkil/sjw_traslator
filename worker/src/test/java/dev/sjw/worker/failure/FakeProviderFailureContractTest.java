package dev.sjw.worker.failure;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import dev.sjw.common.llm.FakeLlmProperties;
import dev.sjw.common.llm.FakeProvider;
import dev.sjw.worker.rate.RetryAfterHint;
import org.junit.jupiter.api.Test;

/**
 * 가짜 provider가 던지는 장애가 워커의 분류기·재시도 힌트에 <b>실 provider와 같은 경로</b>로 읽히는지.
 * 이것이 fake의 존재 이유다 — 429·503을 무료 quota 없이 유발해도 워커 코드가 다른 분기를 타면 의미가 없다.
 */
class FakeProviderFailureContractTest {

    private final FailureClassifier classifier = new FailureClassifier();

    private static FakeProvider provider(Integer rpm, Integer rpd, double errorRate) {
        return new FakeProvider(new FakeLlmProperties(0, 0, rpm, rpd, errorRate, 0.0, null));
    }

    @Test
    void 분당_429는_RATE_LIMITED이고_재시도_힌트가_읽힌다() {
        var p = provider(1, null, 0);
        p.translator("fake-flash-lite").call("x\n\ny");
        var e = assertThrows(FakeProvider.ProviderError.class, () -> p.translator("fake-flash-lite").call("x\n\ny"));
        assertEquals(ErrorClass.RATE_LIMITED, classifier.classify(e));
        assertTrue(RetryAfterHint.parse(e).isPresent(), e.getMessage());
    }

    @Test
    void 일일_429는_QUOTA_DAILY() {
        var p = provider(null, 1, 0);
        p.translator("m").call("x\n\ny");
        var e = assertThrows(FakeProvider.ProviderError.class, () -> p.translator("m").call("x\n\ny"));
        assertEquals(ErrorClass.QUOTA_DAILY, classifier.classify(e));
    }

    @Test
    void overloaded_503은_SERVER_ERROR() {
        var e = assertThrows(FakeProvider.ProviderError.class,
                () -> provider(null, null, 1.0).translator("m").call("x\n\ny"));
        assertEquals(ErrorClass.SERVER_ERROR, classifier.classify(e));
    }
}
