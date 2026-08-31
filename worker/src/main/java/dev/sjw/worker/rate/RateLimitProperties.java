package dev.sjw.worker.rate;

/**
 * 적응형 rate control 파라미터 (§6 "고정 상수 금지").
 *
 * 여기 값들은 운영 rate가 아니라 <b>탐색의 경계와 속도</b>다. 실제 RPM은 429 피드백으로
 * 스스로 정해진다 — initialRpm이 틀려도 몇 번의 429로 교정되는 것이 이 설계의 요점이다.
 *
 * @param initialRpm          버킷 최초 생성 시 시작 RPM (탐색 시작점)
 * @param minRpm              하한 — 아무리 429를 맞아도 여기 밑으로는 안 내려간다
 * @param maxRpm              상한 — 성공이 계속돼도 여기 위로는 안 올라간다
 * @param burstSeconds        버킷 용량 = 이 초 수만큼의 발행량 (rpm * burstSeconds / 60, 최소 1)
 * @param decreaseFactor      429 1회당 곱셈 감소율 (AIMD의 MD)
 * @param successesToIncrease 이 횟수만큼 연속 성공하면 1단계 증가 (AIMD의 AI 트리거)
 * @param increaseStep        증가 폭 (RPM)
 * @param maxWaitMs           permit 대기 상한. 넘으면 메시지를 미ACK로 되돌려 큐가 백오프를 흡수한다
 */
public record RateLimitProperties(
        int initialRpm,
        int minRpm,
        int maxRpm,
        int burstSeconds,
        double decreaseFactor,
        int successesToIncrease,
        int increaseStep,
        long maxWaitMs) {

    public RateLimitProperties {
        if (minRpm < 1 || maxRpm < minRpm) {
            throw new IllegalArgumentException("rate 범위가 잘못됨: min=" + minRpm + ", max=" + maxRpm);
        }
        if (decreaseFactor <= 0 || decreaseFactor >= 1) {
            throw new IllegalArgumentException("decreaseFactor는 (0,1) 구간이어야 함: " + decreaseFactor);
        }
    }
}
