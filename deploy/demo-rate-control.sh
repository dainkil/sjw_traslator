#!/usr/bin/env bash
# 적응형 rate control 데모 (M2 수용 기준 3/3):
#   "429 유발 시 rate가 자동 하향되고, 회복 후 상향된다"를 실호출로 증명한다.
#
# 인위적인 mock 429는 쓰지 않는다. 무료 티어의 실제 분당 한도가 유발 장치다 —
# 시작 rate(설정 initial-rpm)를 provider 실제 한도보다 높게 두면 429가 자연히 발생하고,
# AIMD가 한도 밑으로 수렴시킨 뒤 다시 조금씩 올린다.
#
# 전제: docker compose up, NER(:8100), api(:8080), worker(:8081) 실행 중, 루트 .env에 키.
# 비용: 무료 quota를 N회(기본 30) 소모한다. N=10 처럼 줄여 실행 가능 (하향만 보고 싶을 때).
set -euo pipefail
cd "$(dirname "$0")/.."

API=localhost:8080
WORKER=localhost:8081
REDIS="docker exec sjw-redis redis-cli"
PSQL="docker exec sjw-postgres psql -U sjw -d sjw -t -A -c"

MODEL="${GEMINI_MODEL:-gemini-3.1-flash-lite}"
BUCKET="rate:bucket:$MODEL"
N="${N:-30}"                 # 번역 문장 수 = 소모할 무료 quota 상한
OFFSET="${OFFSET:-200}"      # eval300 코퍼스 내 시작 위치 (demo-resume.sh와 겹치지 않게)
TIMEOUT="${TIMEOUT:-900}"
OUT="${OUT:-/tmp/sjw-rate-timeline.tsv}"

metric429() {
  curl -s "$WORKER/actuator/metrics/llm.rate_limit.429" 2>/dev/null | python3 -c "
import json, sys
try:
    print(int(json.load(sys.stdin)['measurements'][0]['value']))
except Exception:
    print(0)
" 2>/dev/null || echo 0
}

echo "== 0) 전제 확인"
curl -sf "$WORKER/actuator/health" > /dev/null || { echo "worker(:8081)가 없다"; exit 1; }
curl -sf "$API/actuator/health"  > /dev/null 2>&1 || curl -sf "$API/api/v1/batches/00000000-0000-0000-0000-000000000000" > /dev/null 2>&1 || true
echo "   model=$MODEL, 문장=$N, 버킷=$BUCKET"

echo "== 1) 버킷 초기화 (설정 initial-rpm에서 탐색 시작)"
$REDIS DEL "$BUCKET" > /dev/null
BASE429=$(metric429)
echo "   삭제 완료. 누적 429 카운터 기준선=$BASE429"

echo "== 2) 배치 생성: ${N}문장"
B=$(curl -s -X POST $API/api/v1/batches -H 'Content-Type: application/json' \
  -d "{\"offset\":$OFFSET,\"limit\":$N,\"budgetLimitCalls\":$N}")
echo "   $B"
BID=$(echo "$B" | python3 -c "import json,sys; print(json.load(sys.stdin)['batchId'])")

echo "== 3) 버킷 상태 추적 (2초 간격)"
: > "$OUT"
START=$(date +%s)
while :; do
  NOW=$(date +%s); T=$((NOW - START))
  RPM=$($REDIS HGET "$BUCKET" rpm || true)
  TOK=$($REDIS HGET "$BUCKET" tokens || true)
  STREAK=$($REDIS HGET "$BUCKET" streak || true)
  ST=$($PSQL "SELECT status||' '||done_count||' '||failed_count FROM batch_job WHERE id='$BID'")
  STATUS=$(echo "$ST" | awk '{print $1}'); DONE=$(echo "$ST" | awk '{print $2}'); FAILED=$(echo "$ST" | awk '{print $3}')
  C429=$(metric429); D429=$((C429 - BASE429))
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$T" "${RPM:-}" "${TOK:-}" "${DONE:-0}" "${FAILED:-0}" "$D429" "${STATUS:-}" >> "$OUT"
  printf "   [%4ds] rpm=%-4s tokens=%-6s streak=%-3s done=%s/%s failed=%s 429=%s %s\n" \
    "$T" "${RPM:-·}" "${TOK:0:5}" "${STREAK:-·}" "${DONE:-0}" "$N" "${FAILED:-0}" "$D429" "${STATUS:-}"

  case "${STATUS:-}" in
    COMPLETED|BUDGET_EXHAUSTED|QUOTA_PAUSED) break;;
  esac
  if [ "$T" -ge "$TIMEOUT" ]; then echo "   타임아웃(${TIMEOUT}s) — 관측된 데까지 판정한다"; break; fi
  sleep 2
done

echo
echo "== 4) 판정 (타임라인: $OUT)"
python3 - "$OUT" <<'PY'
import sys

rows = []
for line in open(sys.argv[1]):
    p = line.rstrip("\n").split("\t")
    if len(p) < 7 or not p[1]:
        continue
    rows.append({"t": int(p[0]), "rpm": int(float(p[1])), "done": int(p[3]),
                 "failed": int(p[4]), "c429": int(p[5]), "status": p[6]})

if not rows:
    print("❌ 버킷 상태가 한 번도 관측되지 않았다 (워커가 호출을 시작했는지 확인)")
    sys.exit(1)

start_rpm = rows[0]["rpm"]
min_rpm = min(r["rpm"] for r in rows)
i_min = next(i for i, r in enumerate(rows) if r["rpm"] == min_rpm)
after_min = rows[i_min:]
recovered = max((r["rpm"] for r in after_min), default=min_rpm)
n429 = rows[-1]["c429"]

# 변화 지점만 압축해 보여준다 (rpm이 바뀐 순간들)
print("   rate 변화:")
prev = None
for r in rows:
    if prev is None or r["rpm"] != prev:
        print(f"     t={r['t']:>4}s  rpm={r['rpm']:<4} done={r['done']:<3} 429누적={r['c429']}")
        prev = r["rpm"]
print(f"     t={rows[-1]['t']:>4}s  종료: {rows[-1]['status']} "
      f"done={rows[-1]['done']} failed={rows[-1]['failed']}")

print()
print(f"   시작 rate      : {start_rpm} RPM")
print(f"   최저 rate      : {min_rpm} RPM (t={rows[i_min]['t']}s)")
print(f"   최저 이후 최고 : {recovered} RPM")
print(f"   관측된 429     : {n429}건")

down = min_rpm < start_rpm
up = recovered > min_rpm
if down and up:
    print(f"\n✅ 증명 완료: 429 피드백으로 {start_rpm}→{min_rpm} RPM 자동 하향, 이후 {recovered} RPM으로 재상향")
elif down:
    print(f"\n⚠️  하향({start_rpm}→{min_rpm})은 증명됐으나 상향 구간이 관측되지 않았다.")
    print("    연속 성공이 successes-to-increase에 도달하기 전에 배치가 끝났을 수 있다 — N을 늘려 재실행.")
    sys.exit(2)
elif n429 == 0:
    print("\n⚠️  429가 한 번도 발생하지 않았다 (현재 초당 처리 속도가 provider 한도 아래).")
    print("    sjw.rate.initial-rpm을 올리거나 워커를 2대 띄워 재실행하면 유발된다.")
    sys.exit(2)
else:
    print("\n❌ 429가 있었는데 rate가 내려가지 않았다 — 피드백 경로 점검 필요")
    sys.exit(1)
PY
