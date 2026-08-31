package dev.sjw.common.job;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class TranslationJobRepository {

    private static final RowMapper<JobRow> MAPPER = TranslationJobRepository::map;

    private final JdbcClient jdbc;

    public TranslationJobRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    private static JobRow map(ResultSet rs, int rowNum) throws SQLException {
        return new JobRow(
                rs.getObject("id", UUID.class),
                rs.getString("idempotency_key"),
                rs.getString("source_text"),
                rs.getObject("doc_year", Integer.class),
                rs.getString("normalized_hash"),
                JobStatus.valueOf(rs.getString("status")),
                rs.getString("model_used"),
                rs.getObject("tokens_in", Integer.class),
                rs.getObject("tokens_out", Integer.class),
                rs.getObject("batch_id", UUID.class),
                rs.getString("error_class"),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("completed_at", OffsetDateTime.class)
        );
    }

    public void insertPending(UUID id, String idempotencyKey, String sourceText, Integer docYear,
                              String normalizedHash, UUID batchId) {
        jdbc.sql("""
                INSERT INTO translation_job
                  (id, idempotency_key, source_text, doc_year, normalized_hash, status, batch_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """)
                .params(id, idempotencyKey, sourceText, docYear, normalizedHash,
                        JobStatus.PENDING.name(), batchId)
                .update();
    }

    public Optional<JobRow> findById(UUID id) {
        return jdbc.sql("SELECT * FROM translation_job WHERE id = ?")
                .params(id).query(MAPPER).optional();
    }

    public Optional<JobRow> findByIdempotencyKey(String key) {
        return jdbc.sql("SELECT * FROM translation_job WHERE idempotency_key = ?")
                .params(key).query(MAPPER).optional();
    }

    /** PENDING/FAILED → RUNNING 전이에 성공한 경우에만 true — 동시 소비 경합의 1차 방어선. */
    public boolean tryMarkRunning(UUID id) {
        return jdbc.sql("""
                UPDATE translation_job SET status = 'RUNNING'
                WHERE id = ? AND status IN ('PENDING', 'FAILED')
                """)
                .params(id).update() == 1;
    }

    public void markSucceeded(UUID id, String model, String cacheHitLevel,
                              Integer tokensIn, Integer tokensOut, String kbVersion) {
        jdbc.sql("""
                UPDATE translation_job
                SET status = 'SUCCEEDED', model_used = ?, cache_hit_level = ?,
                    tokens_in = ?, tokens_out = ?, kb_version = ?, completed_at = now()
                WHERE id = ?
                """)
                .params(model, cacheHitLevel, tokensIn, tokensOut, kbVersion, id)
                .update();
    }

    public void markFailed(UUID id, JobStatus status, String errorClass) {
        jdbc.sql("UPDATE translation_job SET status = ?, error_class = ?, completed_at = now() WHERE id = ?")
                .params(status.name(), errorClass, id)
                .update();
    }

    public void insertResult(UUID jobId, String translatedText, String entitiesJson, String spansJson) {
        jdbc.sql("""
                INSERT INTO translation_result (job_id, translated_text, entities, uncertain_spans)
                VALUES (?, ?, CAST(? AS jsonb), CAST(? AS jsonb))
                ON CONFLICT (job_id) DO NOTHING
                """)
                .params(jobId, translatedText, entitiesJson, spansJson)
                .update();
    }

    public Optional<String> findResultJson(UUID jobId) {
        return jdbc.sql("""
                SELECT translated_text FROM translation_result WHERE job_id = ?
                """)
                .params(jobId).query(String.class).optional();
    }
}
