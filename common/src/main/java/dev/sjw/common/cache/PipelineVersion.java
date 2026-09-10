package dev.sjw.common.cache;

/**
 * 캐시 무효화의 기준이 되는 파이프라인 버전 (ADR-009 개정, M3-S2).
 *
 * <p>번역 결과의 품질을 결정하는 축은 넷이다 — 인물 사전, 지시문, NER 모델, 번역 LLM.
 * 앞의 셋은 값이 데이터에서 파생되므로 <b>바뀌면 키가 저절로 갈린다</b>. 네 번째(LLM)는
 * 키에서 제외하고(ADR-009 원결정: 모델 선택은 서버 몫이고 적재가 게이트 통과분뿐이라
 * 품질 하한이 보장된다) 대신 {@code epoch}을 수동 손잡이로 둔다 — 모델을 갈아끼우고
 * 캐시를 전면 재구축하려면 {@code CACHE_EPOCH}를 올린다.
 *
 * <p>세그먼트를 해시로 뭉치지 않고 그대로 나열하는 이유: Redis에서 키만 보고 무엇이 캐시를
 * 가르고 있는지 읽을 수 있어야 한다. 저절로 일어나는 무효화일수록 눈으로 확인 가능해야 한다.
 */
public record PipelineVersion(String kb, String prompt, String ner, String epoch) {

    public String keySegment() {
        return kb + ":" + prompt + ":" + ner + ":" + epoch;
    }
}
