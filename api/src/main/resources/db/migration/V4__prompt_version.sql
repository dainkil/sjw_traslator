-- M2.5-S7 프롬프트 외부화 (ADR-013의 기준선 확보).
-- prompt_version: 템플릿+패턴 파일 체크섬 파생 — 회귀 비교·A/B의 기준. 자유 문자열 금지 (kb_version과 동일 원칙).
ALTER TABLE translation_job ADD COLUMN prompt_version TEXT;
