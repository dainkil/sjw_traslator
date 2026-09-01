package dev.sjw.common.kb;

/**
 * 무주입 대조군 — 모든 링킹이 MISS. "KB 주입 효과" A/B의 베이스라인이자
 * KB 데이터 없이 기동해야 하는 상황의 degrade 경로.
 */
public class NoOpKnowledgeSource implements KnowledgeSource {

    @Override
    public String version() {
        return "noop";
    }

    @Override
    public KbPerson person(String id) {
        return null;
    }

    @Override
    public LinkResult link(String mention, int currentYear, String contextText) {
        return LinkResult.miss();
    }
}
