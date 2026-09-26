-- 공개 서빙 1차 (PROGRESS §5.0 1-1): 운영자 키(GEMINI_API_KEY)로 도는 경로의 문.
-- 비동기 job·배치는 운영자 키를 쓴다 — 발급 키가 이 경로를 열면 누구나 운영자 무료 quota를 소진한다.
-- 발급 키의 기본값은 false. BYOK 배치는 ADR-020대로 범위 밖이다.
ALTER TABLE tenant ADD COLUMN operator_access BOOLEAN NOT NULL DEFAULT false;

-- default 테넌트는 운영자 자신이다 (로컬·단독 운영 경로 무변경). 공개 모드에선 헤더 없는 요청이
-- default로 떨어지지 않으므로(401) 이 행은 외부에서 닿지 않는다.
UPDATE tenant SET operator_access = true WHERE id = 'default';
