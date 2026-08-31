package dev.sjw.worker.rate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import org.junit.jupiter.api.Test;

/**
 * 힌트 문자열은 실제 429 응답에서 관찰된 두 형태다 (docs/troubleshooting.md §2).
 * 백오프 길이를 우리가 추측하는 것보다 provider가 준 값이 낫다 — §6 "고정 상수 금지"의 연장.
 */
class RetryAfterHintTest {

    @Test
    void 사람용_문장에서_초를_뽑는다() {
        var e = new RuntimeException("429 RESOURCE_EXHAUSTED. quota_metric: "
                + "GenerateRequestsPerMinutePerProjectPerModel. Please retry in 55.6s");
        assertEquals(Duration.ofMillis(55600), RetryAfterHint.parse(e).orElseThrow());
    }

    @Test
    void RetryInfo_필드에서_초를_뽑는다() {
        var e = new RuntimeException("{\"error\":{\"code\":429,\"details\":[{\"@type\":"
                + "\"type.googleapis.com/google.rpc.RetryInfo\",\"retryDelay\":\"41s\"}]}}");
        assertEquals(Duration.ofSeconds(41), RetryAfterHint.parse(e).orElseThrow());
    }

    @Test
    void 원인_체인_안쪽의_힌트도_찾는다() {
        var e = new IllegalStateException("호출 실패", new RuntimeException("429 . Please retry in 3s"));
        assertEquals(Duration.ofSeconds(3), RetryAfterHint.parse(e).orElseThrow());
    }

    @Test
    void 힌트가_없으면_비어있다() {
        var e = new RuntimeException("429 . Your project has exceeded its monthly spending cap.");
        assertTrue(RetryAfterHint.parse(e).isEmpty());
    }

    @Test
    void 비정상적으로_긴_힌트는_5분으로_자른다() {
        var e = new RuntimeException("429 . Please retry in 86400s");
        assertEquals(Duration.ofMinutes(5), RetryAfterHint.parse(e).orElseThrow());
    }
}
