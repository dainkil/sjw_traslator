package dev.sjw.worker.rate;

/**
 * permit 대기가 상한을 넘었거나 대기 중 인터럽트된 경우.
 *
 * 이건 LLM 호출 실패가 아니라 <b>아직 호출하지 않았다</b>는 뜻이다. 그래서 재시도·서킷 통계에서
 * 제외하고(JobProcessor), 메시지는 미ACK로 되돌려 큐의 재전달이 백오프 역할을 하게 한다.
 */
public class RateLimitWaitTimeoutException extends RuntimeException {

    public RateLimitWaitTimeoutException(String message) {
        super(message);
    }
}
