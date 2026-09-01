-- §8.2 데이터 모델 baseline (M2까지의 스키마 — ADR-023).
-- V1 이전에 schema.sql 직접 실행으로 만들어진 기존 DB는 baseline-on-migrate로 버전 1 처리되어
-- 이 파일을 건너뛴다. IF NOT EXISTS는 그 시절의 멱등 실행 흔적으로, 의미상 무해해서 유지한다.
-- 예산 단위: 무료 티어 운영(ADR-016)에서는 원화가 아니라 LLM 호출 수가 예산이다.

CREATE TABLE IF NOT EXISTS translation_job (
    id              UUID PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    source_text     TEXT NOT NULL,
    doc_year        INT,
    normalized_hash TEXT NOT NULL,
    template_hash   TEXT,
    status          TEXT NOT NULL,            -- PENDING | RUNNING | SUCCEEDED | FAILED | DEAD
    tier            TEXT,
    model_used      TEXT,
    cache_hit_level TEXT,
    tokens_in       INT,
    tokens_out      INT,
    cost_krw        NUMERIC(12, 4),
    kb_version      TEXT,
    batch_id        UUID,
    error_class     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS translation_result (
    job_id          UUID PRIMARY KEY REFERENCES translation_job (id),
    translated_text TEXT NOT NULL,
    entities        JSONB,
    uncertain_spans JSONB
);

CREATE TABLE IF NOT EXISTS batch_job (
    id                 UUID PRIMARY KEY,
    range_spec         JSONB NOT NULL,
    budget_limit_calls INT NOT NULL,          -- 배치가 소비할 수 있는 LLM 호출 상한 (§8.1 budget_limit)
    spent_calls        INT NOT NULL DEFAULT 0,
    cursor_checkpoint  INT NOT NULL DEFAULT 0,
    total_count        INT NOT NULL,
    done_count         INT NOT NULL DEFAULT 0,
    failed_count       INT NOT NULL DEFAULT 0,
    status             TEXT NOT NULL,         -- RUNNING | PAUSED | COMPLETED | BUDGET_EXHAUSTED | QUOTA_PAUSED
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 비용 원장: LLM 호출 1회 = 1행. 멱등 증명("중복 호출 0건")의 근거 데이터.
CREATE TABLE IF NOT EXISTS cost_ledger (
    id             BIGSERIAL PRIMARY KEY,
    job_id         UUID NOT NULL,
    model          TEXT NOT NULL,
    tokens_in      INT,
    tokens_out     INT,
    unit_price_in  NUMERIC(12, 6),
    unit_price_out NUMERIC(12, 6),
    cost_krw       NUMERIC(12, 4),
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_batch ON translation_job (batch_id);
CREATE INDEX IF NOT EXISTS idx_job_status ON translation_job (status);
CREATE INDEX IF NOT EXISTS idx_ledger_job ON cost_ledger (job_id);
