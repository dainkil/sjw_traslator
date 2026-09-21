package dev.sjw.common.llm;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 가짜 provider(`provider: fake`)의 동작 손잡이 (sjw.llm.fake.*). 전부 선택 — 비우면 "지연 100ms,
 * quota 무제한, 장애 0"의 얌전한 provider다. 실측 대체가 아니라 <b>실측이 불가능한 조건을 만드는</b>
 * 장치다: 무료 quota를 태우지 않고 429·503·REJECTED를 원하는 비율로 유발한다 (M6 mock, D11).
 *
 * @param latencyMs    호출당 고정 지연. flash-lite 실측 p50 3.0s와 무관한 기본값 — 부하 테스트에서 명시할 것
 * @param jitterMs     지연에 더해지는 균등 난수 상한
 * @param rpm          분당 허용 호출 수 (모델별 슬라이딩 60초 창). 초과 → 429 PerMinute. null = 무제한
 * @param rpd          일일 허용 호출 수 (모델별, UTC 자정 리셋). 초과 → 429 PerDay. null = 무제한
 * @param errorRate    503 overloaded 주입 확률 [0,1]
 * @param dropNameRate 확정 인명 1건을 번역문에서 빠뜨릴 확률 [0,1] — 품질 게이트 REJECTED → 승격 경로 유발
 * @param seed         난수 시드. 주면 같은 호출 순서에서 같은 장애가 재현된다
 */
@ConfigurationProperties("sjw.llm.fake")
public record FakeLlmProperties(
        Integer latencyMs,
        Integer jitterMs,
        Integer rpm,
        Integer rpd,
        Double errorRate,
        Double dropNameRate,
        Long seed) {

    public FakeLlmProperties {
        latencyMs = latencyMs == null ? 100 : latencyMs;
        jitterMs = jitterMs == null ? 0 : jitterMs;
        errorRate = errorRate == null ? 0.0 : errorRate;
        dropNameRate = dropNameRate == null ? 0.0 : dropNameRate;
        if (latencyMs < 0 || jitterMs < 0) {
            throw new IllegalArgumentException("fake 지연은 0 이상: latency=" + latencyMs + " jitter=" + jitterMs);
        }
        if (rpm != null && rpm < 1 || rpd != null && rpd < 1) {
            throw new IllegalArgumentException("fake quota는 1 이상 (무제한이면 비워둘 것): rpm=" + rpm + " rpd=" + rpd);
        }
        if (errorRate < 0 || errorRate > 1 || dropNameRate < 0 || dropNameRate > 1) {
            throw new IllegalArgumentException("fake 주입 확률은 [0,1]: error=" + errorRate + " dropName=" + dropNameRate);
        }
    }

    /** 손잡이를 하나도 안 잡은 기본 상태 (테스트·기본 빈). */
    public static FakeLlmProperties defaults() {
        return new FakeLlmProperties(null, null, null, null, null, null, null);
    }
}
