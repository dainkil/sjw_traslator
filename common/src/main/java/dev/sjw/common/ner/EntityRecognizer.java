package dev.sjw.common.ner;

import java.util.List;

/**
 * NER 포트 (ADR-018). 계약의 핵심은 <b>빈 결과와 장애의 구분</b>이다 —
 * 엔티티가 없으면 빈 리스트, 인식기가 동작 불능이면 {@link NerUnavailableException}.
 * 장애를 빈 결과로 삼키면 KB 무주입 번역이 조용히 SUCCEEDED 되는 사고가 난다 (M2.5 갭 표).
 *
 * 구현 2종: {@link HttpOnnxRecognizer}(운영) / {@link RulePatternRecognizer}(축소판).
 * 교체는 설정(sjw.ner.mode)만으로 한다 — degrade 경로이자 "KB 주입 효과" A/B의 실행 수단.
 */
public interface EntityRecognizer {

    /** 인식기 식별자 — 로그·A/B 기록용 (예: onnx-http, rule-v1). */
    String id();

    List<NerEntity> extract(String text);
}
