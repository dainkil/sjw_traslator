#!/usr/bin/env bash
# 배치 강제 종료 → 재개 데모 (M2 수용 기준):
#   "결과가 저장된 job의 재호출 0건"을 cost_ledger로 증명한다.
#   (LLM 응답 수신~저장 사이에 죽는 in-flight 1건의 재실행은 at-least-once 경계로 허용 — ADR-001)
# 전제: docker compose up, NER(:8100), api(:8080), worker(:8081) 실행 중, 루트 .env에 키.
set -euo pipefail
cd "$(dirname "$0")/.."
API=localhost:8080
PSQL="docker exec sjw-postgres psql -U sjw -d sjw -t -A -c"

echo "== 1) 배치 생성: 12문장, 예산 12호출"
B=$(curl -s -X POST $API/api/v1/batches -H 'Content-Type: application/json' \
  -d '{"offset":100,"limit":12,"budgetLimitCalls":12}')
echo "   $B"
BID=$(echo "$B" | python3 -c "import json,sys; print(json.load(sys.stdin)['batchId'])")

echo "== 2) done_count >= 4 까지 대기"
while :; do
  D=$($PSQL "SELECT done_count FROM batch_job WHERE id='$BID'")
  echo "   done=$D"
  [ "${D:-0}" -ge 4 ] && break
  sleep 2
done

echo "== 3) worker 강제 종료 (kill -9)"
pkill -9 -f "dev.sjw.worker.WorkerApplication" || true
sleep 2
echo "   미ACK pending: $(docker exec sjw-redis redis-cli XPENDING stream:translation workers | head -1)"
echo "   체크포인트: cursor=$($PSQL "SELECT cursor_checkpoint FROM batch_job WHERE id='$BID'") done=$($PSQL "SELECT done_count FROM batch_job WHERE id='$BID'")"

echo "== 4) worker 재시작"
(set -a; source .env; set +a; nohup ./gradlew :worker:bootRun > /tmp/worker-resume.log 2>&1 &)
until curl -s -o /dev/null -w '' localhost:8081/actuator/health 2>/dev/null; do sleep 2; done
echo "   worker UP"

echo "== 5) 배치 완료 대기"
while :; do
  S=$($PSQL "SELECT status||' '||done_count||'/'||total_count FROM batch_job WHERE id='$BID'")
  echo "   $S"
  case "$S" in COMPLETED*|BUDGET_EXHAUSTED*) break;; esac
  sleep 3
done

echo "== 6) 증명: LLM 호출 원장 (cost_ledger)"
TOTAL=$($PSQL "SELECT count(*) FROM cost_ledger l JOIN translation_job j ON j.id=l.job_id WHERE j.batch_id='$BID'")
MAXPER=$($PSQL "SELECT coalesce(max(c),0) FROM (SELECT count(*) c FROM cost_ledger l JOIN translation_job j ON j.id=l.job_id WHERE j.batch_id='$BID' GROUP BY l.job_id) s")
DONE=$($PSQL "SELECT done_count FROM batch_job WHERE id='$BID'")
echo "   완료 문장 $DONE / 총 LLM 호출 $TOTAL / job당 최대 호출 $MAXPER"
if [ "$MAXPER" -le 1 ]; then
  echo "✅ 증명 완료: 저장된 job의 중복 LLM 호출 0건 (job당 원장 행 최대 1)"
else
  echo "❌ 검증 실패: 어떤 job이 ${MAXPER}회 호출됨"
  exit 1
fi
