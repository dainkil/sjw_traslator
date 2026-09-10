package dev.sjw.common.ner;

import java.util.List;
import java.util.Optional;

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

    /**
     * 모델 파생 버전 — M3 캐시 키의 한 축 (ADR-009 개정). {@code KnowledgeSource.version()}과
     * 같은 이유로 <b>모델에서 파생된 값</b>이어야 한다: NER를 재학습해 갈아끼웠는데 캐시가
     * 옛 결과를 계속 내주면 개선분이 캐시에 막혀 사라진다.
     *
     * <p>비어 있을 수 있다 — 원격 인식기라 아직 버전을 못 받아온 상태가 존재한다.
     * 그 경우 캐시는 조회·적재를 건너뛴다(불확실한 키를 만들어 오염시키느니 미스가 낫다).
     */
    Optional<String> version();

    List<NerEntity> extract(String text);
}
