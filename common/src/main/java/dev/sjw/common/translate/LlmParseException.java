package dev.sjw.common.translate;

/**
 * LLM 호출은 성공했으나 구조화 출력 파싱에 실패.
 * 호출이 실제 발생했으므로 usage를 보존해 원장에 기록해야 한다 (중복 과금 회계의 정확성).
 */
public class LlmParseException extends RuntimeException {

    private final String model;
    private final Integer tokensIn;
    private final Integer tokensOut;

    public LlmParseException(String model, Integer tokensIn, Integer tokensOut, Throwable cause) {
        super("구조화 출력 파싱 실패 (model=" + model + ")", cause);
        this.model = model;
        this.tokensIn = tokensIn;
        this.tokensOut = tokensOut;
    }

    public String model() {
        return model;
    }

    public Integer tokensIn() {
        return tokensIn;
    }

    public Integer tokensOut() {
        return tokensOut;
    }
}
