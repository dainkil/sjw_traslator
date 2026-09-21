package dev.sjw.common.routing;

/**
 * §5.1의 "신호 추출 항목" — 전부 <b>LLM 호출 이전에 이미 계산된</b> 값이다.
 * NER과 KB 링킹은 어차피 수행되므로 난이도 분류의 추가 비용이 0이다. 이것이 §5.1의 논지다.
 *
 * @param entities   전체 엔티티 수
 * @param per        PER 수
 * @param loc        LOC 수 (NER 라벨은 PER/LOC/DAT/POH — POS 클래스는 없다, M3-S4 실측)
 * @param dat        DAT 수
 * @param confirmed  링크 확정 PER 수 (SINGLE/TIME/OFFICE)
 * @param kbMiss     역색인 미등재 PER 수 — <b>상위 모델의 대상이 아니다</b>(주입할 지식이 없다).
 *                   KB 확장의 작업 목록이다: 실측 MISS 멘션 44,082건이 표면형 13,586개에 몰려 있고
 *                   그중 87%가 2~3자 실명이다 (docs/benchmarks.md)
 * @param ambiguous  동명이인 후보 잔존 PER 수 — 후보(≤3)가 프롬프트에 주입된 상태이므로
 *                   고르는 일은 추론이고, 상위 모델이 더 잘할 여지가 있다
 * @param formulaic  정형문 패턴 매칭 여부 (prompts/positive-patterns.tsv)
 */
public record RoutingSignals(
        int entities, int per, int loc, int dat,
        int confirmed, int kbMiss, int ambiguous, boolean formulaic) {}
