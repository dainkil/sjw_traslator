package dev.sjw.common.job;

import dev.sjw.common.llm.ModelRegistry;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * LLM 호출 1회 = 1행. "재시작 시 중복 호출 0건"의 증명 데이터 (M2 수용 기준).
 *
 * 단가·비용은 counterfactual 유료 환산이다 — 무료 티어 운영(ADR-016)에서 실지출은 0이지만,
 * "유료였다면 얼마였나"를 행 단위로 남겨야 절감 헤드라인(§9)이 원장에서 직접 집계된다.
 */
@Repository
public class CostLedgerRepository {

    private final JdbcClient jdbc;
    private final ModelRegistry registry;

    public CostLedgerRepository(JdbcClient jdbc, ModelRegistry registry) {
        this.jdbc = jdbc;
        this.registry = registry;
    }

    /** @return 이 호출의 counterfactual 비용 — translation.cost.krw 계측(§9.1)에 쓰인다 */
    public ModelRegistry.Cost record(UUID jobId, String model, Integer tokensIn, Integer tokensOut,
                                     String tenantId) {
        ModelRegistry.Cost cost = registry.cost(model, tokensIn, tokensOut);
        jdbc.sql("""
                INSERT INTO cost_ledger (job_id, model, tokens_in, tokens_out,
                                         unit_price_in, unit_price_out, cost_krw, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """)
                .params(jobId, model, tokensIn, tokensOut,
                        cost.unitPriceIn(), cost.unitPriceOut(), cost.krw(), tenantId)
                .update();
        return cost;
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
