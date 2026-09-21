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
                rs.getString("cache_hit_level"),
                rs.getString("quality_grade"),
                rs.getObject("tokens_in", Integer.class),
                rs.getObject("tokens_out", Integer.class),
                rs.getObject("batch_id", UUID.class),
                rs.getString("tenant_id"),
                rs.getString("error_class"),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("completed_at", OffsetDateTime.class)
        );
    }

    public void insertPending(UUID id, String idempotencyKey, String sourceText, Integer docYear,
                              String normalizedHash, UUID batchId, String tenantId) {
        jdbc.sql("""
                INSERT INTO translation_job
                  (id, idempotency_key, source_text, doc_year, normalized_hash, status, batch_id, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """)
                .params(id, idempotencyKey, sourceText, docYear, normalizedHash,
                        JobStatus.PENDING.name(), batchId, tenantId)
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
                              Integer tokensIn, Integer tokensOut, String kbVersion,
                              String promptVersion, String qualityGrade) {
        jdbc.sql("""
                UPDATE translation_job
                SET status = 'SUCCEEDED', model_used = ?, cache_hit_level = ?,
                    tokens_in = ?, tokens_out = ?, kb_version = ?, prompt_version = ?,
                    quality_grade = ?, completed_at = now()
                WHERE id = ?
                """)
                .params(model, cacheHitLevel, tokensIn, tokensOut, kbVersion, promptVersion,
                        qualityGrade, id)
                .update();
    }

    /**
     * L2 슬롯화의 template_hash 기록 (§8.2 컬럼). <b>L2 on/off와 무관하게</b> 쓴다 —
     * S4의 히트율 시뮬레이션은 "L2를 껐던 기간의 job들이 서로 틀을 공유했는가"를 사후에
     * 계산해야 하고, 그 입력이 이 컬럼이다. 실패한 job에도 남도록 LLM 호출 전에 기록한다.
     */
    public void updateTemplateHash(UUID id, String templateHash) {
        jdbc.sql("UPDATE translation_job SET template_hash = ? WHERE id = ?")
                .params(templateHash, id)
                .update();
    }

    /**
     * 난이도 티어 기록 (§8.2 컬럼, M4-S1). LLM 호출 전에 쓴다 —
     * 실패한 job에도 남아야 §9.1 {@code translation.tier.distribution}과 원장 대조가 성립한다.
     */
    public void updateTier(UUID id, String tier) {
        jdbc.sql("UPDATE translation_job SET tier = ? WHERE id = ?")
                .params(tier, id)
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

    /** 배치 resume 시 FAILED job을 PENDING으로 되돌리고 재발행 대상 id를 반환 (재시도 경로). */
    public java.util.List<UUID> resetFailedToPending(UUID batchId) {
        return jdbc.sql("""
                UPDATE translation_job SET status = 'PENDING', error_class = NULL
                WHERE batch_id = ? AND status = 'FAILED'
                RETURNING id
                """)
                .params(batchId).query(UUID.class).list();
    }

    public Optional<String> findResultJson(UUID jobId) {
        return jdbc.sql("""
                SELECT translated_text FROM translation_result WHERE job_id = ?
                """)
                .params(jobId).query(String.class).optional();
    }
}
