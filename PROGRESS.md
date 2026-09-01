# 진행 상황 & 재개 가이드

> 마지막 갱신: 2026-09-01. 다른 컴퓨터에서 이어서 작업하기 위한 인수인계 문서.
> 전체 설계·수용 기준은 [PROJECT_PLAN.md](PROJECT_PLAN.md), 결정 기록은 [docs/adr/](docs/adr/).

## 1. 로드맵 현황

| 마일스톤 | 상태 | 증거 |
|---|---|---|
| M0 리프레이밍 + 비용/시간 모델 | ✅ 완료 | `docs/cost-model.md` (파라미터화, 토큰 실측 반영) |
| M1 단건 동기 경로 | ✅ 완료 | `docs/benchmarks.md` — LLM이 p95의 99.7~99.9% 확정 |
| M2 비동기 + 배치 엔진 | ✅ 완료 (2026-09-01) | 아래 §3 — 수용 기준 3종 증거 상태 포함 |
| **M2.5 교체 가능성 + 품질 게이트 + 배포 기반** | **신설 (2026-09-01 계획 개정)** | 계획서 §10 M2.5 — M3·M4의 전제 |
| M3 템플릿 슬롯 캐싱 | 예정 | |
| M4 NER 비용 라우팅 | 예정 | |
| M5 비용 SLI + 예산 서킷브레이커 | 예정 | |
| M6 배포/CI/부하테스트 | 예정 | |

## 2. 지금까지의 핵심 실측 (전부 재현 커맨드 포함, docs/benchmarks.md)

- **LLM이 전체 p95의 99.7~99.9%** — 모든 아키텍처 결정의 근거 (§2.1 실측 완료)
- NER ONNX INT8: p50 8.3ms, PER recall 100%, 178MB (GPU 배제 근거, ADR-003)
- 입력 토큰의 ~85%가 프롬프트 오버헤드 (820 중 700) → 컨텍스트 캐싱이 1순위 레버
- 완역 비용: 유료 $842≈118만 원/0.9일 vs **무료 단일 모델(RPD 20 실측) 173년**
- 무료 quota는 **모델별 독립** → 티어 라우팅(M4) = quota 풀링
- 무료 모델 현황: `gemini-3.5-flash`(T1, RPD 20 — 아껴 쓸 것) / `gemini-3.1-flash-lite`(개발 기본, p50 3.0s) / `gemma-4-26b-a4b-it`(혼잡 변동 큼) / `gemini-2.5-flash`(신규 프로젝트 단종 — 404)
- 배치 처리량 **23 jobs/min** (flash-lite) — 워커 1대와 2대가 동일 (23.4 vs 23.1), 중복 호출 0건 → D11(단일 워커)의 실측 근거

## 3. M2 완료분 (S1~S6)

| 단계 | 내용 | 실증 |
|---|---|---|
| S1 | 멀티모듈(common/api/worker) + docker-compose(Redis·Postgres) + §8.2 스키마 4테이블 | 테스트 7건 |
| S2 | Redis Streams 큐: 202 발행→Consumer Group 소비→XACK, 멱등 키, cost_ledger 원장, stale claim 회수 | 비동기 E2E |
| S3 | 배치 엔진: BatchPump(커서 발행), pause/resume, 예산 사전 검증(422) | **`deploy/demo-resume.sh`: kill -9 → 재개 → 12/12, job당 호출 최대 1회 (중복 0건 증명)** |
| S4 | 실패 분류 9종(429를 SPEND_CAP/QUOTA_DAILY/RATE_LIMITED로 3분할), DLQ 적재, Resilience4j retry+서킷, 파싱 실패 시에도 토큰 원장 기록, QUOTA_DAILY 시 배치 자동 일시정지 | 분류기 테스트 8건 + DLQ 실동작 데모(404 유발) |
| S5 | 적응형 rate control: Redis Lua 토큰버킷(멀티워커 공유) + AIMD(429→절반, 연속 성공→+1 RPM), 고정 페이싱 제거 | `deploy/demo-rate-control.sh`, 리미터 테스트 (ADR-017) |
| S6 | 단건 SSE 스트리밍(entities→token→done), 배치 처리량 실측, rate 데모 판정 | benchmarks.md M2 섹션 — 처리량 23 jobs/min, 워커 2배에도 동일, 중복 0건 |

**M2 수용 기준 증거 상태:** ① 강제 종료→재개 중복 0건 = `demo-resume.sh` 라이브 증명 ✅ ② 429→하향→상향 = **라이브 유발 실패** (60 RPM·2워커에서도 429 0건 — provider 유효 한도 미달), AIMD 자체는 실측 429 원문 기반 단위 테스트로 검증, 강제 429 라이브 검증은 M6 mock provider로 이관 ③ DLQ 분류 적재 = 404 유발 라이브 증명 ✅. 상세는 benchmarks.md.

## 4. 새 컴퓨터 셋업 (순서대로)

```bash
git clone https://github.com/dainkil/sjw_traslator.git && cd sjw_traslator

# 1) 비밀키 — 저장소엔 없다. 직접 만들 것:
cp .env.example .env   # GEMINI_API_KEY=<결제 미연동 프로젝트의 키> 로 편집
echo "GEMINI_MODEL=gemini-3.1-flash-lite" >> .env
# 주의: 키는 반드시 '결제 미연동' 프로젝트에서 발급 (ADR-016).
#       키를 바꾸면 모델 탐침을 다시 돌릴 것 (docs/troubleshooting.md §3).

# 2) 인프라
docker compose -f deploy/docker-compose.yml up -d

# 3) NER 서버 (최초 1회 모델 변환 ~700MB 다운로드)
cd ner-server && uv sync && uv run python scripts/export_onnx.py
uv run uvicorn app.main:app --port 8100 &   # :8100
cd ..

# 4) api + worker (Java 21 필요, gradle wrapper 포함)
set -a; source .env; set +a
./gradlew :api:bootRun &      # :8080 (스키마 자동 적용)
./gradlew :worker:bootRun &   # :8081

# 5) 동작 확인
curl -s -X POST localhost:8080/api/v1/translations -H 'Content-Type: application/json' \
  -d '{"text":"傳曰知道","year":1623}'          # → 202 {jobId}
curl -s localhost:8080/api/v1/translations/<jobId> # → SUCCEEDED + 번역
./deploy/demo-resume.sh                            # 강제종료→재개 데모 (12 LLM 호출 소모)
```

**이 컴퓨터에만 있는 것 (커밋 안 됨):** `malmoi/` 원천 데이터 180MB (병렬 코퍼스 70MB 등).
서빙 개발에는 불필요 — 필요한 KB·골든셋은 `kb/`, `eval/`에 커밋되어 있다. M0 코퍼스 통계 재실측이나 M2 인조 1년치 대량 배치를 다른 컴퓨터에서 하려면 이 디렉토리를 별도로 옮겨야 한다.

## 5. 다음 작업 (재개 지점)

> **2026-09-01 계획 개정.** 계획 검토 결과 M3·M4가 둘 다 아직 없는 추상화(모델 레지스트리, 검증된 `kb_version`, 품질 게이트)에 의존한다는 점이 확인되어, **M2.5를 M3 앞에 삽입**했다. 개정 전문은 [PROJECT_PLAN.md](PROJECT_PLAN.md) §5.4 / §10 / §15.

### 5.1 다음: M2.5 — 교체 가능성 + 품질 게이트 + 배포 기반 (5~6일)

계획서 §10 M2.5가 정본이다. **진행 (2026-09-01): S1(Flyway + ADR 6건) · S2(모델 레지스트리 + Translator 포트, 3모델 설정 교체 실증) · S3(EntityRecognizer 포트 http/rule, 골든셋 A/B 수치 확보) · S4(KnowledgeSource 포트, 정조 KB 기동 실증, 체크섬 버전, ADR-018) · S5(품질 게이트: quality_grade + T1 승격 + 오탐률 3.9% 선측정 + score_db.py 기준선 chrF 41.52/인명 99.09%, ADR-019) · S6(BYOK/테넌트: X-Api-Key 해시 식별 + 일일 상한 429 + rate:bucket:{tenant}:{model} + X-Llm-Key 요청 단위 클라이언트·비저장 검증, ADR-020 — 단, BYOK는 동기/SSE만, 배치는 운영자 키) 완료 — 수용 기준 1·2·3·4(런타임 게이트)·6(어댑터) 충족.** 요약:

1. **포트 3종** `Translator` / `EntityRecognizer` / `KnowledgeSource` — 각각 실구현 2개 이상. 구현체 1개짜리 인터페이스는 만들지 않는다
2. **모델 레지스트리** `sjw.llm.models[]{id, provider, tier, rpd, 단가}` — rate 버킷 키·원장 단가·M4 티어 매핑·quota 풀링의 단일 출처. `CostLedgerRepository`의 단가 0 하드코딩을 유료 환산값으로 교체
3. **품질 게이트** (§5.4) — 런타임 `quality_grade`(VERIFIED/DEGRADED/REJECTED) + `eval/score_300.py`의 DB 어댑터 + 비열등 임계(chrF −2.0, 인명 재현율 하락 0, 층화 n=60 3회 중앙값)
4. **BYOK / 테넌트 격리** — 요청 단위 LLM 클라이언트, `rate:bucket:{tenant}:{model}`, 키는 저장하지 않음
5. **프롬프트 외부화** — `PromptAssembler`의 Java 상수 템플릿을 리소스 파일로, `prompt_version` 기록
6. **배포 기반** — Dockerfile 3종(NER은 INT8 178MB를 이미지에 굽는다), 최소 CI(테스트·빌드), Flyway, §9.1 메트릭 계측 착수
7. **배포 타겟 확정** — Oracle Cloud Always Free(ARM) 우선, 불가 시 self-host+CI로 축소 → ADR-022

**현재 코드의 착수 지점 (검토에서 확인된 갭):**

| 대상 | 파일 | 문제 |
|---|---|---|
| ~~모델 하드바인딩~~ | `TranslationService` | ✅ S2 해소 — `Translator` 포트 + `common/llm` 레지스트리, 모델은 호출마다 옵션 지정 |
| ~~NER 교체 불가~~ | `EntityRecognizer` | ✅ S3 해소 — http/rule 2구현 + `NerUnavailableException`(장애≠빈 결과) + `NER_UNAVAILABLE` 분류 |
| ~~KB 파일명 고정~~ | `KnowledgeSource` | ✅ S4 해소 — file(injo/jeongjo)/noop 구현, version = 파일 체크섬 파생 |
| ~~품질 게이트 부재~~ | `QualityGate` | ✅ S5 해소 — quality_grade 판정 + REJECTED→T1 승격 + 오탐률 3.9% 선측정 + score_db.py 비열등 판정 |
| ~~단가 미기록~~ | `CostLedgerRepository` | ✅ S2 해소 — 레지스트리 단가로 counterfactual 원화 기록 (행 단위) |

### 5.2 미작성 ADR

**작성 완료 (2026-09-01, M2.5-S1):** 004(KB in-memory) / 007(Tool Calling 배제) / 008(ChatMemory 배제) / 012(Kafka·MSA·K8s 배제) / 021(단일 워커 — 처리량 실측 근거) / 023(Flyway).
**남은 M2.5 산출물:** 022(배포 타겟) — 018(S4)·019(S5)·020(S6) 작성 완료. 009~011·013은 M3~M5에서.

## 6. 세션 운영 규칙 (Claude Code로 재개할 때)

- **단계별 보고 → 사용자 승인 → 커밋.** 승인 없이 커밋하지 않는다.
- **커밋에 Claude 관련 표기 금지** (Co-Authored-By, 세션 링크 등).
- 모든 성능·비용 주장은 실측 기반, 추정은 `(추정)` 표기 (계획서 원칙 4).
- 새 의존성 = ADR 작성. §7 배제 목록(RAG·Kafka·K8s 등) 도입 전 반드시 사용자 확인.
- LLM 호출은 무료 quota를 아껴서: 개발·데모는 `gemini-3.1-flash-lite`, 3.5-flash는 하루 20회뿐.
- 트러블슈팅 선례: `docs/troubleshooting.md` (429 3종, Vertex 모드 함정, 모델 가용성).
