package dev.sjw.common.llm;

import reactor.core.publisher.Flux;

/**
 * LLM 호출 포트 (ADR-018). 경계는 "프롬프트 in → 원문 텍스트 + usage out"까지다 —
 * Structured Output 파싱·엔티티 병합은 도메인(TranslationService)의 일이므로 여기 두지 않는다.
 *
 * 구현 교체 축은 provider가 아니라 <b>모델</b>이다: 같은 어댑터가 레지스트리의 모델 id로
 * 파라미터화되며, 교체는 설정(sjw.llm.active-model)만으로 일어난다 (M2.5 수용 기준 3).
 */
public interface Translator {

    /** 이 인스턴스가 호출하는 모델 id — rate 버킷 키·원장 기록의 기준. */
    String modelId();

    /** 동기 호출. 파싱 실패 시에도 과금 회계가 가능하도록 usage를 항상 동반한다. */
    LlmReply call(String prompt);

    /** 토큰 스트리밍 (SSE 경로, D7). */
    Flux<String> stream(String prompt);

    record LlmReply(String text, Integer tokensIn, Integer tokensOut) {}
}
