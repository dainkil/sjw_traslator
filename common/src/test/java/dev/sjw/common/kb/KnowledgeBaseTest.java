package dev.sjw.common.kb;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/**
 * 실제 KB 파일 대상, Python 원본(kb/data_ContextInjection.py)과의 동작 일치 검증.
 * 고정값은 kb/inverted_index_injo.json에서 확인한 실데이터다.
 */
class KnowledgeBaseTest {

    static KnowledgeBase kb;

    @BeforeAll
    static void load() throws IOException {
        kb = new KnowledgeBase("../kb", "injo-v1-test");
    }

    @Test
    void 단일_후보는_1단계에서_확정된다() {
        LinkResult r = kb.link("李元翼", 1623, "領議政李元翼");
        assertEquals(LinkResult.Stage.SINGLE, r.stage());
        assertEquals("이원익", kb.person(r.resolvedId()).hangulName());
    }

    @Test
    void 복수_후보는_활동시기_필터로_단일화된다() {
        // 강선: M_0000012(활동_시작 1563) vs M_0000013(활동_시작 1645)
        LinkResult r = kb.link("강선", 1600, "문맥 없음");
        assertEquals(LinkResult.Stage.TIME, r.stage());
        assertEquals("M_0000012", r.resolvedId());
    }

    @Test
    void 시간으로_못_가르면_관직_문맥_매칭으로_단일화된다() {
        LinkResult r = kb.link("강선", 1650, "부수찬으로 제수하였다");
        assertEquals(LinkResult.Stage.OFFICE, r.stage());
        assertEquals("M_0000013", r.resolvedId());
    }

    @Test
    void 한문_원문_문맥에서도_관직_한자표기로_매칭된다() {
        // 서빙 입력은 한문 원문 — KB 관직 "부수찬(副修撰)"의 괄호 안 한자로 매칭돼야 한다
        LinkResult r = kb.link("강선", 1650, "以姜銑爲副修撰");
        assertEquals(LinkResult.Stage.OFFICE, r.stage());
        assertEquals("M_0000013", r.resolvedId());
    }

    @Test
    void 모두_실패하면_상위3_복수후보_반환() {
        LinkResult r = kb.link("선", 1650, "무관한 문맥");
        assertEquals(LinkResult.Stage.AMBIGUOUS, r.stage());
        assertTrue(r.candidateIds().size() <= 3 && !r.candidateIds().isEmpty());
    }

    @Test
    void 미등재_표층형은_MISS() {
        LinkResult r = kb.link("존재하지않는이름", 1623, "");
        assertEquals(LinkResult.Stage.MISS, r.stage());
    }
}
