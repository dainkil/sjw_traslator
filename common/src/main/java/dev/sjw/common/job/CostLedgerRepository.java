package dev.sjw.common.job;

import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/** LLM 호출 1회 = 1행. "재시작 시 중복 호출 0건"의 증명 데이터 (M2 수용 기준). */
@Repository
public class CostLedgerRepository {

    private final JdbcClient jdbc;

    public CostLedgerRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public void record(UUID jobId, String model, Integer tokensIn, Integer tokensOut) {
        // 무료 티어(ADR-016): 단가 0. 유료 전환 시 unit_price·cost_krw를 모델별 단가로 채운다.
        jdbc.sql("""
                INSERT INTO cost_ledger (job_id, model, tokens_in, tokens_out,
                                         unit_price_in, unit_price_out, cost_krw)
                VALUES (?, ?, ?, ?, 0, 0, 0)
                """)
                .params(jobId, model, tokensIn, tokensOut)
                .update();
    }

    public long countCallsForJob(UUID jobId) {
        return jdbc.sql("SELECT count(*) FROM cost_ledger WHERE job_id = ?")
                .params(jobId).query(Long.class).single();
    }

    public long countCallsForBatch(UUID batchId) {
        return jdbc.sql("""
                SELECT count(*) FROM cost_ledger l
                JOIN translation_job j ON j.id = l.job_id
                WHERE j.batch_id = ?
                """)
                .params(batchId).query(Long.class).single();
    }
}
