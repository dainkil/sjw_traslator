-- M2.5-S5 품질 게이트 (§5.4, ADR-019).
-- quality_grade: VERIFIED | DEGRADED | REJECTED — 런타임 결정론 판정 결과.
-- REJECTED 행이 곧 검수 큐다 (티어 승격 후에도 실패한 건).
ALTER TABLE translation_job ADD COLUMN quality_grade TEXT;
CREATE INDEX idx_job_quality ON translation_job (quality_grade);
