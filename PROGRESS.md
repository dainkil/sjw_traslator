# 진행 상황 & 재개 가이드

> 마지막 갱신: 2026-09-11. 다른 컴퓨터에서 이어서 작업하기 위한 인수인계 문서.
> 전체 설계·수용 기준은 [PROJECT_PLAN.md](PROJECT_PLAN.md), 결정 기록은 [docs/adr/](docs/adr/).

## 1. 로드맵 현황

| 마일스톤 | 상태 | 증거 |
|---|---|---|
| M0 리프레이밍 + 비용/시간 모델 | ✅ 완료 | `docs/cost-model.md` (파라미터화, 토큰 실측 반영) |
| M1 단건 동기 경로 | ✅ 완료 | `docs/benchmarks.md` — LLM이 p95의 99.7~99.9% 확정 |
| M2 비동기 + 배치 엔진 | ✅ 완료 (2026-09-01) | 아래 §3 — 수용 기준 3종 증거 상태 포함 |
| M2.5 교체 가능성 + 품질 게이트 + 배포 기반 | ✅ 완료 (2026-09-01) | §5.1 수용 기준 판정 — 포트 3종·품질 게이트·BYOK·compose 전 스택 |
| M3 템플릿 슬롯 캐싱 | ✅ **완료 (2026-09-11)** | S1 슬롯 로직 / S2 L1 라이브 / S3 L2 라이브 / S4 히트율 **17.36% 실측** / S5 비열등 **통과** — 수용 기준 판정은 §5.1.2 |
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

# 지름길 (M2.5-S8): NER 모델을 한 번 export해 두면 전 스택이 컨테이너로 뜬다 —
#   cd ner-server && uv sync && uv run python scripts/export_onnx.py && cd ..
#   docker compose -f deploy/docker-compose.yml up -d --build
# 아래 2)~4)는 로컬 gradle 개발 경로다.

# 2) 인프라만
docker compose -f deploy/docker-compose.yml up -d redis postgres

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

### 5.1 M3 진행 (현재 재개 지점)

계획서 §10의 M3가 정본. 5슬라이스로 쪼갰다.

- **S1 완료 (2026-09-01, `01a0e0f`)** — `TemplateSlotter`(확정 PER만 슬롯화, 등장 위치 순 번호,
  조사 보정 5쌍, 경계 검사) + `CacheKeys`/`CacheLevel` + **ADR-009**(무효화 A안: 버전을 캐시 키에
  포함 → 무효화 코드 0줄, 적재 정책 = L1은 게이트 통과분만 / L2는 VERIFIED + 전체형 출현분만).
- **S2 완료 (2026-09-10)** — L1 캐시 라이브. 워커·동기·SSE 경로 통합, `cache_hit_level` 기록,
  `translation.cache.hit/miss` 계측, `deploy/demo-cache.sh`.
  실측은 `docs/benchmarks.md` — **job 2건에 원장 1행**, 히트 지연 0~12ms vs 미스 1,665ms.

  S2에서 **ADR-009를 개정**했다. 원결정의 키는 `kb_version`·`prompt_version`뿐이었는데, 품질을
  결정하는 축은 넷(인물 사전·지시문·**NER 모델**·번역 LLM)이고 NER 모델에는 버전 개념이 아예
  없었다. NER 재학습본으로 갈아끼워도 캐시가 옛 결과를 계속 내주면 **개선분이 캐시에 막혀
  사라지고 등급으로도 안 드러난다.** 그래서:
  - 키를 `{kb}:{prompt}:{ner}:{epoch}` 파이프라인 버전으로 확장 (`PipelineVersions`)
  - NER 서버가 `/healthz`에 `model_version`(가중치 SHA-256 앞 8자리) 노출 → 자동 무효화
  - 번역 LLM은 여전히 키에서 제외하고 **`CACHE_EPOCH` 수동 손잡이**로 전면 재구축
  - `NER_MODE`/`KB_NAME`/`CACHE_EPOCH`를 compose passthrough로 노출 (교체 실증 수단)

  결정 근거(사용자, 2026-09-10): 캐시는 **테넌트 간 전역 공유**하되 BYOK 결과는 적재 제외,
  동기 경로도 게이트를 붙여 적재, 캐시 히트는 테넌트 일일 상한을 소모하지 않는다(예산 단위 =
  LLM 호출 수).

- **S3 완료 (2026-09-11)** — L2 템플릿 슬롯 캐시 라이브 (`CACHE_L2_ENABLED=true`, **기본 off**).
  워커·동기·SSE 3경로 통합. 실측은 `docs/benchmarks.md` "L2 템플릿 슬롯 캐시".

  라이브 증거 (`deploy/demo-l2-cache.sh`, `以{인물}爲承旨`의 인물만 교체한 쌍):
  - `以兪榥爲承旨` → `유황을 승지로 제수하였다.` 적재 → 템플릿 `⟪PER1⟫을 승지로 제수하였다.`
  - `以金瑬爲承旨` → **`김류를 승지로 제수하였다.`** — LLM 0회, **조사 `을`→`를` 보정 라이브 확인**
  - job 2건에 `cost_ledger` **1행**, 히트 등급 **DEGRADED**, `tokens_in` NULL
  - 마커 제거 고장 주입 → `reinject.abort{structure_mismatch}` + 전체 파이프라인 fallback (원장 1행)
  - **opt-in 실증**: 틀이 Redis에 있는 상태로 L2를 끄고 요청 → LLM이 처리(797 tok),
    `hit/miss{level=L2}` 둘 다 미생성(꺼둔 것은 미스가 아니다), `template_hash`는 기록됨
  - 단계별 지연: L2 히트 ≈42ms (**ner 31 + cache 4.8**, 워밍 후 ≈23ms) vs 미스 2,450ms.
    **L1(0~12ms)보다 느린 것이 정상** — L2는 슬롯화에 링크 확정 PER이 필요해 NER을 건너뛰지 못한다.

  ADR-009는 개정하지 않고 **구현 메모**를 덧붙였다 (원결정이 정하지 않았던 4건):
  ① 재주입 결과에도 게이트를 통과시킨다(공짜 결정론 검사 — 불합격은 재주입 로직 회귀 신호)
  ② `template_hash`는 L2 on/off와 무관하게 기록한다(S4가 기능을 켜지 않고 효과를 추정하므로)
  ③ L2 히트를 L1으로 승격 적재하지 않는다(껐을 때 즉시 멈춰야 한다 — 스위치의 의미)
  ④ 테넌트 과금을 LLM 호출 직전으로 내렸다(`TenantGuard.ensureWithinCap`이 문 앞을 막는다).
  새 메트릭: `translation.cache.reinject.abort{reason}` (§9.1 표에 추가).

- **S4 완료 (2026-09-11)** — 히트율 실측 + 비용 비교표. `eval/simulate_cache.py` (LLM 호출 **0회**).
  히트율은 코퍼스·NER·KB의 성질이고 번역 LLM과 무관하므로, 6만 문장을 실제 번역하지 않고
  **순차 재생**(생산 코드와 같은 L1→L2→LLM 순서 + 적재 정책)으로 측정했다. 전문은
  `docs/benchmarks.md` "캐시 히트율 + 캐시 on/off 비용 비교".

  | | A01 (1,911문장) | 인조 전수 (62,056문장) |
  |---|---|---|
  | L1 구조적 반복 | 17.84% | 15.65% |
  | L2 구조적 반복 (전체 중) | 0.73% | 2.77% |
  | **실효 히트율 L1+L2** | **18.21%** | **17.36%** |
  | L2 순 기여 | +0.37%p | **+1.74%p** |
  | 비용 (Flash counterfactual) | 2,437 → 1,993원 | 79,146 → 65,409원 |

  - **L2는 코퍼스가 커질수록 기여가 커진다** (1년치 0.37%p → 23년치 1.74%p). 1년치만 보고 판단하면
    과소평가한다. L1은 규모와 함께 단조 증가하며 6.2만에서도 상승 중 → 잔여 코퍼스엔 보수적 하한.
  - **L2가 L1 히트를 317건 잡아먹는다** (승격 적재를 안 하므로). 순효과 +1,075 절감 —
    "L2를 끄면 즉시 멈춘다"는 보장의 대가가 호출 0.51%로 측정됐다.
  - `docs/cost-model.md`의 `캐시 히트율` 파라미터를 0%(가정 40%) → **17.4%(실측)** 로 교체.
    **가정 40%는 반증됐다.** 캐시만으로 무료 축은 173년 → 143년(17%)뿐이고,
    **완역 시간의 지배 변수는 캐시가 아니라 quota다 → 남은 레버는 M4 티어 라우팅.**
  - **이식 충실도 2중 검증**: 생산 DB 대조(`normalized_hash` 96건, `template_hash` 9건 전부 일치,
    `--self-check`는 불일치 시 exit 1) + 골든셋 게이트 오탐률 **3.9% 정확 재현**.

  **부수 발견 3건:**
  1. **NER 모델에 POS(관직) 클래스가 없다** — 라벨은 `PER/LOC/DAT/POH`. 계획서 §5.2의
     "인명/날짜/관직"과 `命{PER}爲{POS}` 예시가 모델과 불일치 → §5.2에 정정 주석.
  2. **슬롯 확장의 기회는 관직이 아니라 지명이다** — 반복 틀 상한 PER 2.77% / PER+LOC **13.86%**(5배)
     / +관직 15.63%(+1.8%p). **ADR-009의 재검토 조건을 개정**했다(전제도 역어 사전이 아니라 지명 KB).
  3. **원천 코퍼스의 원문↔번역 짝이 밀려 있다** (전수 11.24%, A01 20.67%). 게이트 REJECTED가
     골든셋(3.9%)과 7배 어긋나 추적한 결과 데이터 결함. 밀림 제외 후 4.36%로 일치.
     골든셋 300은 영향 없다. 선례: `docs/troubleshooting.md` §5. 검출기는 시뮬레이터에 포함.
     **런타임 품질 게이트가 코퍼스 정합성 검사기로 동작한 사례.**

  재현: `python3 eval/simulate_cache.py --years all --self-check` (NER 서버 필요, 첫 실행 846초 —
  NER 결과는 `eval/.ner_cache_*.json`에 캐시되어 재실행은 즉시. 캐시는 gitignore).

### 5.1.1 L2 활성화 결정 — **off 유지** (사용자 결정, 2026-09-11)

S4 실측을 보고 **L2를 기본 off로 유지**하기로 했다. 근거는 교환 조건의 크기다:

| L2가 사는 것 (전수 62,056문장) | L2가 내는 대가 |
|---|---|
| LLM 호출 −1,075회 (+1.74%p) | **DEGRADED 등급 1,392건** — LLM이 쓰지 않은 문장이 서빙된다 |
| 비용 66,780 → 65,409원 (−2.1%) | L1 히트 317건 잠식 (승격 적재를 안 하므로) |
| 완역 유료 99.6 → 97.5만원 | 재주입 실패·조사 보정이라는 추가 실패 표면의 유지 비용 |
| 완역 무료 **146년 → 143년 (3년)** | |

**173년 중 3년을 위해 "LLM이 쓰지 않은 번역"을 서빙하는 교환은, 인명 정확도가 존재 이유인
프로젝트에 맞지 않는다.** 코드·테스트·데모·계측은 전부 보존한다 — 기능을 못 만든 것이 아니라
만들어서 재보고 이 조건에서는 수혜가 작다고 판정한 것이고, 그 판정이 계획서 §13이 말하는
유효한 결과다. 코퍼스가 커지면 기여가 커지므로(1년치 0.37%p → 23년치 1.74%p) 재검토 여지는 남는다.

**L2의 값은 현재 슬롯 범위가 아니라 범위 확장에 있다** — 지명(LOC)까지 슬롯화하면 반복 틀이
2.77% → 13.86%(5배)다. 막힌 것은 인식이 아니라(NER이 LOC를 33,469건 검출한다) **한자 지명 →
한글 지명 정본**이고, 지명 KB가 새로 필요하다. ADR-009 재검토 조건에 반영했다. M3 범위 밖.

- **S5 완료 (2026-09-11)** — L2 비열등 판정 **통과**. `eval/score_l2.py` (신규).
  **생산 코드 경로로 측정했다** — L2 결과를 이식으로 근사하지 않고 실행 중인 api의
  `TranslationCache.lookupL2`+`TemplateSlotter.reinject`+`QualityGate`가 만들게 하고
  `meta.cacheHit == "L2_TEMPLATE"` 확인분만 표본에 넣었다. 쌍당 3요청(F를 LLM 번역→틀 적재 /
  R은 L2 히트 / 틀 삭제 후 R을 LLM 직접 = 대조군), LLM 2회.

  | 지표 | 임계(§5.4) | 실측 중앙값 | 판정 |
  |---|---|---|---|
  | chrF | −2.0 이내 | **+0.04** (2차) / −1.28 (1차) / 6라운드 −1.13 | ✅ |
  | 확정 인명 재현율 | **하락 0** | **±0.0000** (6라운드 전부 양쪽 1.0000) | ✅ |

  - 표본 풀 = S4 L2 히트 1,392쌍 중 **정렬 검증 통과 1,220쌍**(`--dump-l2-pairs`). 층화 패턴×길이 7개 층.
  - **"3회 중앙값" 규정이 실제로 일했다**: 1차 R1이 −2.20으로 임계를 넘었다. 단일 측정이면 위반이
    나왔을 것이다. 6라운드 범위 −2.20~+0.70 = LLM 비결정성이 chrF 3포인트 폭을 만든다.
  - 기록 `eval/l2_noninferiority.json`, 종료 코드 계약은 `score_db.py`와 동일(위반=1) → M6 CI 연결 가능.
  - **판정 통과에도 L2는 off 유지** (§5.1.1 결정 불변). 품질이 아니라 수혜 크기가 근거이며,
    ADR-009 "운영 상태"에 "품질이 나빠서 끈 것이 아니다"를 명시했다.

  **S5 부수 실측 2건 (헤드라인을 바꿨다):**
  1. **`gemini-3.1-flash-lite` 무료 quota 실측 — RPD 500 / RPM 15.** 429 응답 본문의 `quotaValue`가
     직접 알려줬다(3.5-flash RPD 20을 확정한 것과 같은 방법). 42건 전부 `quotaDimensions.model`이
     flash-lite다. **무료 축 완역 시간이 173년 → 6.9년(캐시 17.4% 반영 5.7년)으로 25배 바뀐다** —
     기존 173년은 RPD 20짜리 T1 단독이라는 최악 조건이었다. `docs/cost-model.md` 갱신.
     **이것이 M4의 값을 구체화한다**: quota가 모델별 독립이므로 풀링하면 500+20+(gemma-4 미측정)이
     하루 예산이고, 완역 시간은 캐시가 아니라 이 합계가 정한다.
     또 **M2에서 유발 실패했던 라이브 429가 여기서 자연 발생했다**(M6 mock 이관 항목의 근거 데이터).
     **미해소 모순**: M2의 배치 처리량 23 jobs/min이 RPM 15를 넘는데 그때는 429 0건이었다
     (quota 변경/버스트 허용/측정 창 중 미확증) → M6 재측정. AIMD `initial-rpm: 20`·`max-rpm: 60`도
     실측 15를 넘어 **M4 재조정 후보**다.
  2. **동기 경로에 rate limiter·재시도·실패 분류가 없다** — 429 42건이 전부 HTTP 500으로 나갔다.
     워커만 ADR-017+Resilience4j+`FailureClassifier` 9종을 갖고 있다. 측정 도구가 페이싱·재시도를
     대신 지고 있고, **429를 본문 문자열로 판별해야 한다는 것이 갭의 증거**다.
     처리 방향(`FailureClassifier`를 common으로 + `@ExceptionHandler`로 429/503 매핑)은
     `docs/troubleshooting.md` §6. 곁가지로 **`cost_ledger`가 job 단위(`job_id NOT NULL`)라 동기 경로
     호출은 원장에 안 남는다** — 예산은 테넌트 카운터가 지키지만 **M5 비용 SLI는 두 출처 합산 필요**.

### 5.1.2 M3 수용 기준 최종 판정 (2026-09-11)

계획서 §10 M3 기준 3종 + 추가 1종.

1. **인조 1년치 실측 L1/L2 히트율 확보** — ✅ A01 L1 17.84% / L2 0.73% / 실효 18.21%.
   전수 23년치도 확보(L1 15.65% / L2 2.77% / 실효 17.36%) + 배치 규모별 추이.
2. **캐시 on/off 비용 비교표** — ✅ 전수 62,056문장: off 79,146원 / L1만 66,780원 / L1+L2 65,409원.
   `cost-model.md`의 캐시 히트율 파라미터를 0%(가정 40%)에서 **17.4% 실측**으로 교체.
3. **재주입 실패 탐지 → fallback** — ✅ 라이브 고장 주입으로 증명(`deploy/demo-l2-cache.sh`):
   마커 제거 → `reinject.abort{structure_mismatch}` + 전체 파이프라인 재실행(원장 1행).
   게이트를 재주입 결과에도 걸어 두 번째 방어선을 만들었다(ADR-009 구현 메모 1).
4. **추가: L2 히트가 §5.4 비열등 임계 통과** — ✅ chrF +0.04 / 인명 재현율 ±0.
   **단, 통과에도 L2는 off로 유지**한다(수혜 1.74%p). 계획서 §13의 "시도했고 이 조건에서는
   수혜가 작다"는 결과 형태로 기록했다.

- **다음: M4 — NER 비용 라우팅.** S4·S5가 M4의 값을 수치로 만들어 놨다:
  완역 시간의 지배 변수가 캐시(17.4%)가 아니라 **모델별 quota**이고, 그 quota가 모델별로 독립이라
  풀링이 곧 시간 단축이다(flash-lite 500 + 3.5-flash 20 + gemma-4 미측정).
  착수 전 확인할 것: ① gemma-4 등 나머지 모델의 RPD/RPM을 429 `quotaValue`로 실측
  ② AIMD 기본값(`initial-rpm: 20`/`max-rpm: 60`)을 실측 RPM 15 기준으로 재조정
  ③ 라우팅 신호는 이미 있다 — `LinkResult.Stage`(SINGLE/TIME/OFFICE/AMBIGUOUS/MISS)와 NER 검출 수.

**S2에서 발견한 별건 갭 (M5로 이월):** `/actuator/prometheus`가 404다 —
`micrometer-registry-prometheus`가 없어 노출 설정만 있고 레지스트리가 없다. 카운터 자체는
`/actuator/metrics`로 확인된다. Grafana 대시보드를 세우는 M5에서 붙인다.

### 5.2 M2.5 완료 기록

계획서 §10 M2.5가 정본이다. **진행 (2026-09-01): S1(Flyway + ADR 6건) · S2(모델 레지스트리 + Translator 포트, 3모델 설정 교체 실증) · S3(EntityRecognizer 포트 http/rule, 골든셋 A/B 수치 확보) · S4(KnowledgeSource 포트, 정조 KB 기동 실증, 체크섬 버전, ADR-018) · S5(품질 게이트: quality_grade + T1 승격 + 오탐률 3.9% 선측정 + score_db.py 기준선 chrF 41.52/인명 99.09%, ADR-019) · S6(BYOK/테넌트: X-Api-Key 해시 식별 + 일일 상한 429 + rate:bucket:{tenant}:{model} + X-Llm-Key 요청 단위 클라이언트·비저장 검증, ADR-020 — 단, BYOK는 동기/SSE만, 배치는 운영자 키) · S7(프롬프트 외부화: 템플릿·패턴 리소스 파일 + prompt_version 체크섬 파생, 외부화 전후 프롬프트 바이트 동일 확인 tokens_in 754 불변) · S8(Dockerfile 3종 — NER은 INT8 174MB 동봉, compose 전 스택 라이브 E2E, GitHub Actions CI 테스트→빌드, §9.1 메트릭 이름 정렬 + cost/tokens/latency/ner.unavailable 계측, ADR-022 배포 타겟 = Oracle Always Free 우선) 완료.**

**M2.5 수용 기준 최종 판정 (2026-09-01):**
1. KB 정조 교체 기동, 코드 0줄 — ✅ 라이브 (`jeongjo-2abe1183`, 蔡濟恭 링크)
2. NER 규칙 교체 + 품질 차이 수치 — ✅ 골든셋 recall 26.9% vs ONNX 100% (`NER_MODE=rule` 라이브 E2E)
3. 모델 3종 설정 교체 — ✅ flash-lite·3.5-flash 라이브 200 (gemma-4는 라우팅 성공·응답은 혼잡 무응답 — 실측된 provider 특성, 교체 경로는 동일)
4. REJECTED 검출 + 상위 티어 승격 + 오탐률 측정 — 게이트·승격 경로 구현 + 단위 테스트, 오탐률 3.9% 실측 ✅. **단, 라이브 REJECTED 자연 발생은 아직 미관측** (기준선 인명 재현율 99.09%라 드묾 — 운영 중 시계열로 확인)
5. compose 전 스택 기동 — ✅ 라이브 (5컨테이너, 컨테이너 파이프라인 E2E SUCCEEDED. 이미지: api 604MB / worker 600MB / ner 973MB)
6. 골든셋 채점 DB 직결 + 비열등 임계 판정 — ✅ `score_db.py` (위반 시 exit 1). **CI 스케줄 연결은 결과 DB가 생기는 배포(M6) 이후** — ci.yml 주석에 명시

요약:

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

### 5.3 미작성 ADR

**작성 완료 (2026-09-01, M2.5-S1):** 004(KB in-memory) / 007(Tool Calling 배제) / 008(ChatMemory 배제) / 012(Kafka·MSA·K8s 배제) / 021(단일 워커 — 처리량 실측 근거) / 023(Flyway).
**남은 M2.5 산출물:** 022(배포 타겟) — 018(S4)·019(S5)·020(S6) 작성 완료. 009~011·013은 M3~M5에서.

## 6. 세션 운영 규칙 (작업 재개 시)

- **단계별 보고 → 사용자 승인 → 커밋.** 승인 없이 커밋하지 않는다.
- **커밋 메시지에 도구·에이전트 표기 금지** (Co-Authored-By, 세션 링크 등).
- 모든 성능·비용 주장은 실측 기반, 추정은 `(추정)` 표기 (계획서 원칙 4).
- 새 의존성 = ADR 작성. §7 배제 목록(RAG·Kafka·K8s 등) 도입 전 반드시 사용자 확인.
- LLM 호출은 무료 quota를 아껴서: 개발·데모는 `gemini-3.1-flash-lite`, 3.5-flash는 하루 20회뿐.
- 트러블슈팅 선례: `docs/troubleshooting.md` (429 3종, Vertex 모드 함정, 모델 가용성).
