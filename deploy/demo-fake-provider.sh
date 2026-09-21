#!/usr/bin/env bash
# 가짜 LLM provider 데모 (M6 mock — ADR-018 재검토 조건 "두 번째 provider" 이행). 무료 quota 0.
#   A) 배치 완주   — 실 호출 0, 게이트 VERIFIED, 원장에 fake 모델·단가 0, 캐시 적재 0 (가짜는 캐시에 안 들어간다)
#   B) 429 유발    — FAKE_RPM으로 분당 한도를 흉내 → RATE_LIMITED 분류 + 적응형 리미터 하향 → 완주
#                    (M2 수용 기준 ②: 60RPM×2워커로도 못 만들던 라이브 429를 mock으로 만든다는 이관 항목)
#   C) REJECTED 유발 → 승격 — FAKE_DROP_NAME_RATE로 확정 인명을 빠뜨림 → 게이트 REJECTED → fake-flash 승격 재호출
# 사용: deploy/demo-fake-provider.sh A|B|C     (N=문장 수, 기본 60. api는 SJW_EVAL_CORPUS 골든셋을 읽고 있어야 한다)
# 주의: 워커를 재기동한다 — 진행 중인 실 배치가 있으면 먼저 pause. 끝나면 기본 env로 되돌릴 것:
#       docker compose -f deploy/docker-compose.yml up -d --no-deps worker
set -euo pipefail
cd "$(dirname "$0")/.."
API=localhost:8080
PSQL="docker exec sjw-postgres psql -U sjw -d sjw -t -A -c"
REDIS="docker exec sjw-redis redis-cli"
SCENARIO=${1:-A}
N=${N:-60}

case "$SCENARIO" in
  A) ENV="FAKE_LATENCY_MS=100";;
  B) ENV="FAKE_LATENCY_MS=100 FAKE_RPM=${FAKE_RPM:-20}";;
  C) ENV="FAKE_LATENCY_MS=100 FAKE_DROP_NAME_RATE=${FAKE_DROP_NAME_RATE:-0.3} FAKE_SEED=42 TIER_UP_ENABLED=true TIER_UP_MODEL=fake-flash";;
  *) echo "usage: $0 A|B|C"; exit 2;;
esac
[ "$SCENARIO" = C ] || ENV="$ENV TIER_UP_ENABLED=false"

echo "== 0) 워커를 가짜 provider로 재기동: GEMINI_MODEL=fake-flash-lite $ENV (캐시 off)"
env GEMINI_MODEL=fake-flash-lite CACHE_L1_ENABLED=false CACHE_L2_ENABLED=false $ENV \
  docker compose -f deploy/docker-compose.yml up -d --no-deps worker >/dev/null 2>&1   # --no-deps: api를 기본 env로 재생성하지 않는다
until docker logs sjw-worker 2>&1 | grep -q "Started WorkerApplication"; do sleep 2; done
docker exec sjw-worker env | grep -E '^(GEMINI_MODEL|FAKE_|TIER_UP)' | sed 's/^/   /'

REAL_BEFORE=$($PSQL "SELECT count(*) FROM cost_ledger WHERE model NOT LIKE 'fake-%'")
L1_BEFORE=$($REDIS --scan --pattern 'cache:l1:*' | wc -l | tr -d ' ')
L2_BEFORE=$($REDIS --scan --pattern 'cache:l2:*' | wc -l | tr -d ' ')
LOG_MARK=$(docker logs sjw-worker 2>&1 | wc -l | tr -d ' ')
T0=$(date +%s)

echo "== 1) 배치 생성: ${N}문장, 예산 $((N*2))호출"
B=$(curl -s -X POST $API/api/v1/batches -H 'Content-Type: application/json' \
  -d "{\"offset\":0,\"limit\":$N,\"budgetLimitCalls\":$((N*2))}")
BID=$(echo "$B" | python3 -c "import json,sys; print(json.load(sys.stdin)['batchId'])")
echo "   batch $BID"

echo "== 2) 완료 대기"
while :; do
  S=$($PSQL "SELECT status||' '||done_count||'/'||total_count||' failed='||failed_count FROM batch_job WHERE id='$BID'")
  printf '   %s\r' "$S"
  case "$S" in COMPLETED*|BUDGET_EXHAUSTED*|QUOTA_PAUSED*) echo; break;; esac
  sleep 3
done
echo "   소요 $(( $(date +%s) - T0 ))s"

echo "== 3) 결과"
echo "   job 모델×등급:"; $PSQL "SELECT '     '||coalesce(model_used,'-')||'  '||coalesce(quality_grade,'-')||'  '||count(*) FROM translation_job WHERE batch_id='$BID' GROUP BY 1 ORDER BY 1" 2>/dev/null || \
  $PSQL "SELECT coalesce(model_used,'-'), coalesce(quality_grade,'-'), count(*) FROM translation_job WHERE batch_id='$BID' GROUP BY 1,2 ORDER BY 1,2" | sed 's/^/     /'
echo "   원장(이 배치) 모델별 행·비용:"; $PSQL "SELECT l.model, count(*), sum(l.cost_krw) FROM cost_ledger l JOIN translation_job j ON j.id=l.job_id WHERE j.batch_id='$BID' GROUP BY 1" | sed 's/^/     /'
echo "   실 모델 원장 증가: $(( $($PSQL "SELECT count(*) FROM cost_ledger WHERE model NOT LIKE 'fake-%'") - REAL_BEFORE ))  (기대 0)"
echo "   캐시 키 증가: L1 $(( $($REDIS --scan --pattern 'cache:l1:*' | wc -l | tr -d ' ') - L1_BEFORE ))  L2 $(( $($REDIS --scan --pattern 'cache:l2:*' | wc -l | tr -d ' ') - L2_BEFORE ))  (기대 0 — 가짜는 적재 금지)"
echo "   워커 로그(이 배치 구간): 429 $(docker logs sjw-worker 2>&1 | tail -n +$((LOG_MARK+1)) | grep -c '429' || true)건, RATE_LIMITED $(docker logs sjw-worker 2>&1 | tail -n +$((LOG_MARK+1)) | grep -c 'RATE_LIMITED' || true)건, 승격 $(docker logs sjw-worker 2>&1 | tail -n +$((LOG_MARK+1)) | grep -c '승격' || true)건"
if [ "$SCENARIO" = B ]; then
  echo "   리미터 조정 로그:"; docker logs sjw-worker 2>&1 | tail -n +$((LOG_MARK+1)) | grep -iE 'rpm|rate' | grep -viE 'RATE_LIMITED' | head -8 | cut -c1-160 | sed 's/^/     /'
fi
if [ "$SCENARIO" = C ]; then
  echo "   승격 로그(앞 5건):"; docker logs sjw-worker 2>&1 | tail -n +$((LOG_MARK+1)) | grep '승격' | head -5 | cut -c1-170 | sed 's/^/     /'
fi
echo "== 끝. 되돌리기: docker compose -f deploy/docker-compose.yml up -d --no-deps worker (기본 env)"
