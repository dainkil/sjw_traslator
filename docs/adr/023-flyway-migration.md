# ADR-023: 스키마 마이그레이션 도구(Flyway) 도입

- 상태: 승인 (M2.5-S1에서 구현)
- 날짜: 2026-09-01

## 배경

M2까지는 `schema.sql`(CREATE IF NOT EXISTS)을 api 기동 시 매번 실행했다. 테이블 신설만 있는 동안은 멱등해서 충분했다.
M2.5부터 **기존 테이블 변경**이 시작된다 — tenant/quality_grade/prompt_version 컬럼 추가(§8.2) — IF NOT EXISTS로는 ALTER를 표현할 수 없고, "이 DB에 어떤 변경까지 적용됐나"를 추적하지 않으면 기존 dev DB와 신규 DB의 스키마가 갈라진다.

## 선택지

1. **Flyway** — 버전 붙은 SQL 파일 + 적용 이력 테이블
2. Liquibase — changelog(XML/YAML) 추상화
3. 수동 ALTER 스크립트 누적

## 결정

**선택지 1.** 구성:

- `V1__baseline.sql` = 기존 schema.sql 그대로 (M2까지의 스키마).
- `baseline-on-migrate: true` — V1 이전 방식으로 이미 만들어진 DB는 버전 1로 기준선 처리되어 V1을 건너뛰고, 빈 DB는 V1부터 실행된다. 두 경로 모두 검증함.
- 마이그레이션 실행 주체는 **api 단독** (worker는 `sql.init: never` 유지) — 두 프로세스가 경쟁 적용하는 구조를 만들지 않는다.
- 이후 모든 스키마 변경은 `db/migration/V{n}__*.sql`로만 한다.

근거: 스키마가 순수 SQL 3테이블 + 원장이라 SQL-first 도구가 정확히 맞고, Spring Boot 자동 구성으로 코드 0줄이며, CI(M2.5-S8)에서 빈 DB 재현이 마이그레이션 실행만으로 보장된다.

## 버린 대안과 그 이유

- **Liquibase(2)**: changelog 추상화의 가치는 다중 DBMS 지원인데 이 프로젝트는 PostgreSQL 고정이다. 단일 DB에서 XML 간접층은 읽을 것만 늘린다.
- **수동 스크립트(3)**: "어느 DB에 어디까지 적용했나"가 사람 기억에 의존한다. 지금 두 대의 개발 머신이 같은 스키마를 봐야 하는 상황 자체가 이 방식의 반례다.

## 재검토 조건

- 사실상 없음 (업계 표준 관행). 파괴적 변경의 롤백이 요구되면 undo 전략(별도 down 마이그레이션)을 그때 설계한다.
