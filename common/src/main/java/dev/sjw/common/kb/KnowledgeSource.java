package dev.sjw.common.kb;

/**
 * 인물 KB 포트 (ADR-018). 구현: {@link FileKnowledgeSource}(인조/정조 — 데이터 파일 교체) /
 * {@link NoOpKnowledgeSource}(무주입 대조군·degrade). 교체는 설정(sjw.kb.*)만으로 한다 (M2.5 수용 기준 1).
 *
 * version()은 캐시 무효화(M3)의 키가 되므로 <b>데이터에서 파생된 값</b>이어야 한다 —
 * 자유 문자열 버전은 데이터가 바뀌어도 안 바뀔 수 있어 신뢰 근거가 없다.
 */
public interface KnowledgeSource {

    /** 데이터 파생 버전 (예: injo-3f2a9c1e — 이름 + 데이터 파일 체크섬). */
    String version();

    KbPerson person(String id);

    LinkResult link(String mention, int currentYear, String contextText);
}
