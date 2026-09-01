package dev.sjw.common.job;

import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class BatchJobRepository {

    private static final RowMapper<BatchRow> MAPPER = (rs, n) -> new BatchRow(
            rs.getObject("id", UUID.class),
            rs.getString("range_spec"),
            rs.getInt("budget_limit_calls"),
            rs.getInt("cursor_checkpoint"),
            rs.getInt("total_count"),
            rs.getInt("done_count"),
            rs.getInt("failed_count"),
            rs.getString("status"));

    private final JdbcClient jdbc;

    public BatchJobRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public void insert(UUID id, String rangeSpecJson, int budgetLimitCalls, int totalCount,
                       String tenantId) {
        jdbc.sql("""
                INSERT INTO batch_job (id, range_spec, budget_limit_calls, total_count, status, tenant_id)
                VALUES (?, CAST(? AS jsonb), ?, ?, 'RUNNING', ?)
                """)
                .params(id, rangeSpecJson, budgetLimitCalls, totalCount, tenantId)
                .update();
    }

    public Optional<BatchRow> findById(UUID id) {
        return jdbc.sql("SELECT * FROM batch_job WHERE id = ?").params(id)
                .query(MAPPER).optional();
    }

    public List<BatchRow> findByStatus(String status) {
        return jdbc.sql("SELECT * FROM batch_job WHERE status = ?").params(status)
                .query(MAPPER).list();
    }

    /** 상태 전이는 기대 상태 일치 시에만 (경합 방어). true = 전이됨 */
    public boolean transition(UUID id, String from, String to) {
        return jdbc.sql("UPDATE batch_job SET status = ?, updated_at = now() WHERE id = ? AND status = ?")
                .params(to, id, from).update() == 1;
    }

    public void setStatus(UUID id, String to) {
        jdbc.sql("UPDATE batch_job SET status = ?, updated_at = now() WHERE id = ?")
                .params(to, id).update();
    }

    public void updateProgress(UUID id, int cursor, int done, int failed) {
        jdbc.sql("""
                UPDATE batch_job SET cursor_checkpoint = ?, done_count = ?, failed_count = ?,
                       updated_at = now() WHERE id = ?
                """)
                .params(cursor, done, failed, id).update();
    }

    /** [SUCCEEDED 수, FAILED/DEAD 수] */
    public int[] terminalCounts(UUID batchId) {
        return jdbc.sql("""
                SELECT count(*) FILTER (WHERE status = 'SUCCEEDED') AS ok,
                       count(*) FILTER (WHERE status IN ('FAILED','DEAD')) AS bad
                FROM translation_job WHERE batch_id = ?
                """)
                .params(batchId)
                .query((rs, n) -> new int[]{rs.getInt("ok"), rs.getInt("bad")})
                .single();
    }

    public Optional<UUID> jobIdByIndex(UUID batchId, int index) {
        return jdbc.sql("SELECT id FROM translation_job WHERE idempotency_key = ?")
                .params(batchKey(batchId, index))
                .query(UUID.class).optional();
    }

    public static String batchKey(UUID batchId, int index) {
        return "batch:" + batchId + ":" + index;
    }
}
