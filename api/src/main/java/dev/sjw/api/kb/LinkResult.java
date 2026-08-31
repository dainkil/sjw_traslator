package dev.sjw.api.kb;

import java.util.List;

/**
 * 링킹 결과. stage는 어느 단계에서 해소됐는지 — 티어 라우팅(M4)의 신호로 쓰인다.
 */
public record LinkResult(Stage stage, List<String> candidateIds) {

    public enum Stage {
        SINGLE,     // 1단계: 역색인 단일 후보
        TIME,       // 2단계: 활동시기 필터로 단일화
        OFFICE,     // 3단계: 관직-문맥 매칭으로 단일화
        AMBIGUOUS,  // 복수 후보 잔존 (상위 3)
        MISS        // 역색인 미등재
    }

    public boolean resolved() {
        return stage == Stage.SINGLE || stage == Stage.TIME || stage == Stage.OFFICE;
    }

    public String resolvedId() {
        return resolved() ? candidateIds.getFirst() : null;
    }

    public static LinkResult miss() {
        return new LinkResult(Stage.MISS, List.of());
    }
}
