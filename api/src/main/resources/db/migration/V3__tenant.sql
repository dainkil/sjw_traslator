-- M2.5-S6 BYOK / 멀티테넌트 (D10, ADR-020).
-- api_key_hash: 발급형 X-Api-Key의 SHA-256. BYOK LLM 키(X-Llm-Key)는 어떤 테이블에도 저장하지 않는다.
CREATE TABLE tenant (
    id               TEXT PRIMARY KEY,
    display_name     TEXT,
    api_key_hash     TEXT UNIQUE,
    daily_call_limit INT NOT NULL DEFAULT 200,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 개발·단독 운영의 기본 테넌트 (X-Api-Key 없는 요청). 공개 배포 시 비활성화 대상 (M6).
INSERT INTO tenant (id, display_name, api_key_hash, daily_call_limit)
VALUES ('default', '운영자 기본', NULL, 1000);

ALTER TABLE translation_job ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE batch_job       ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE cost_ledger     ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX idx_ledger_tenant ON cost_ledger (tenant_id);
