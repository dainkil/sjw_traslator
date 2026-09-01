package dev.sjw.common.ner;

/**
 * NER 인식기 동작 불능 (서버 다운·타임아웃·비정상 응답). LLM 장애와 반드시 구분해야 한다 —
 * 메시지 텍스트로 분류하면 NER 타임아웃이 LLM TIMEOUT으로 오귀속되어 서킷브레이커 통계를 오염시킨다.
 */
public class NerUnavailableException extends RuntimeException {

    public NerUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }

    public NerUnavailableException(String message) {
        super(message);
    }
}
