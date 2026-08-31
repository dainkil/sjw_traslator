package dev.sjw.worker.failure;

import static org.junit.jupiter.api.Assertions.assertEquals;

import dev.sjw.common.translate.LlmParseException;
import org.junit.jupiter.api.Test;

/**
 * 분류 근거 문자열은 2026-08-31 실제 발생 로그에서 가져왔다 (docs/troubleshooting.md).
 * HTTP 429 하나가 세 가지 전혀 다른 운영 상황을 실어 나른다 — 이 테스트가 그 증거.
 */
class FailureClassifierTest {

    private final FailureClassifier c = new FailureClassifier();

    @Test
    void 지출상한_429는_SPEND_CAP() {
        var e = new RuntimeException("429 . Your project has exceeded its monthly spending cap. "
                + "Please go to AI Studio at https://ai.studio/spend");
        assertEquals(ErrorClass.SPEND_CAP, c.classify(e));
    }

    @Test
    void 일일quota_429는_QUOTA_DAILY() {
        var e = new RuntimeException("429 RESOURCE_EXHAUSTED. You exceeded your current quota. "
                + "quota_metric: GenerateRequestsPerDayPerProjectPerModel, quotaValue: 20");
        assertEquals(ErrorClass.QUOTA_DAILY, c.classify(e));
    }

    @Test
    void 분당_429는_RATE_LIMITED() {
        var e = new RuntimeException("429 RESOURCE_EXHAUSTED. quota_metric: "
                + "GenerateRequestsPerMinutePerProjectPerModel. Please retry in 55.6s");
        assertEquals(ErrorClass.RATE_LIMITED, c.classify(e));
    }

    @Test
    void 모델단종_404는_MODEL_UNAVAILABLE() {
        var e = new RuntimeException("404 NOT_FOUND. This model models/gemini-2.5-flash "
                + "is no longer available");
        assertEquals(ErrorClass.MODEL_UNAVAILABLE, c.classify(e));
    }

    @Test
    void 혼잡_503은_SERVER_ERROR() {
        var e = new RuntimeException("503 UNAVAILABLE. This model is currently experiencing high demand");
        assertEquals(ErrorClass.SERVER_ERROR, c.classify(e));
    }

    @Test
    void 타임아웃() {
        var e = new RuntimeException("The read operation timed out");
        assertEquals(ErrorClass.TIMEOUT, c.classify(e));
    }

    @Test
    void 파싱실패는_원인체인_어디에_있어도_PARSE_ERROR() {
        var e = new RuntimeException("wrapper",
                new LlmParseException("m", 800, 100, new IllegalStateException("bad json")));
        assertEquals(ErrorClass.PARSE_ERROR, c.classify(e));
    }

    @Test
    void 미분류는_UNKNOWN() {
        assertEquals(ErrorClass.UNKNOWN, c.classify(new RuntimeException("???")));
    }
}
