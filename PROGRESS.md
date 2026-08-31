# 진행 상황 & 재개 가이드

> 마지막 갱신: 2026-08-31. 다른 컴퓨터에서 이어서 작업하기 위한 인수인계 문서.
> 전체 설계·수용 기준은 [PROJECT_PLAN.md](PROJECT_PLAN.md), 결정 기록은 [docs/adr/](docs/adr/).

## 1. 로드맵 현황

| 마일스톤 | 상태 | 증거 |
|---|---|---|
| M0 리프레이밍 + 비용/시간 모델 | ✅ 완료 | `docs/cost-model.md` (파라미터화, 토큰 실측 반영) |
| M1 단건 동기 경로 | ✅ 완료 | `docs/benchmarks.md` — LLM이 p95의 99.7~99.9% 확정 |
| **M2 비동기 + 배치 엔진** | **S1~S4 완료, S5·S6 남음** | 아래 §3 |
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

## 3. M2 완료분 (S1~S4)

| 단계 | 내용 | 실증 |
|---|---|---|
| S1 | 멀티모듈(common/api/worker) + docker-compose(Redis·Postgres) + §8.2 스키마 4테이블 | 테스트 7건 |
| S2 | Redis Streams 큐: 202 발행→Consumer Group 소비→XACK, 멱등 키, cost_ledger 원장, stale claim 회수 | 비동기 E2E |
| S3 | 배치 엔진: BatchPump(커서 발행), pause/resume, 예산 사전 검증(422) | **`deploy/demo-resume.sh`: kill -9 → 재개 → 12/12, job당 호출 최대 1회 (중복 0건 증명)** |
| S4 | 실패 분류 9종(429를 SPEND_CAP/QUOTA_DAILY/RATE_LIMITED로 3분할), DLQ 적재, Resilience4j retry+서킷, 파싱 실패 시에도 토큰 원장 기록, QUOTA_DAILY 시 배치 자동 일시정지 | 분류기 테스트 8건 + DLQ 실동작 데모(404 유발) |

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

## 5. 다음 작업 (재개 지점): M2-S5 — 적응형 rate control

구현 명세 (계획서 §6 "고정 상수 금지"):

1. Redis 키 `rate:bucket:{model}`에 토큰 버킷 상태(용량·잔여·최근 보충 시각). 워커는 LLM 호출 전 Lua 스크립트로 원자적 permit 획득 (멀티 워커 공유).
2. **AIMD**: 429(RATE_LIMITED 분류) 피드백 → rate 절반(하한 2 RPM), 성공 N회 연속 → +1 RPM (상한 설정값). `FailureClassifier`가 이미 429를 분류하므로 `JobProcessor.onFailure`의 RATE_LIMITED 경로에 버킷 하향 훅만 걸면 된다.
3. `StreamConsumer`의 **임시 고정 페이싱(`sjw.worker.pace-ms`, 3초)을 제거**하고 버킷 대기로 대체 — 코드에 "S5에서 대체" 주석이 표시돼 있다.
4. 검증(M2 수용 기준): 429 유발 시 rate 자동 하향 → 회복 후 상향. 무료 티어에선 quota 소진이 자연 유발 수단 (인위 mock 불필요). 데모 스크립트로 기록.

이후 **M2-S6**: 단건 SSE 스트리밍(Spring AI `stream()`), `docs/benchmarks.md`에 배치 처리량 실측 추가, M2 수용 기준 3종 데모 정리, README 진행표 갱신 → M2 완료 push.

## 6. 세션 운영 규칙 (Claude Code로 재개할 때)

- **단계별 보고 → 사용자 승인 → 커밋.** 승인 없이 커밋하지 않는다.
- **커밋에 Claude 관련 표기 금지** (Co-Authored-By, 세션 링크 등).
- 모든 성능·비용 주장은 실측 기반, 추정은 `(추정)` 표기 (계획서 원칙 4).
- 새 의존성 = ADR 작성. §7 배제 목록(RAG·Kafka·K8s 등) 도입 전 반드시 사용자 확인.
- LLM 호출은 무료 quota를 아껴서: 개발·데모는 `gemini-3.1-flash-lite`, 3.5-flash는 하루 20회뿐.
- 트러블슈팅 선례: `docs/troubleshooting.md` (429 3종, Vertex 모드 함정, 모델 가용성).
