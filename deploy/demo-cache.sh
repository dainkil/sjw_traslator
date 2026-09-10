#!/usr/bin/env bash
# L1 캐시 데모 (M3-S2 수용 근거):
#   같은 문장을 두 번 요청하면 두 번째는 LLM·NER 호출이 0회다.
#   증명은 cost_ledger — job은 2건인데 원장 행은 1건이어야 한다.
#   그리고 파이프라인 버전(NER 모델 / epoch)이 바뀌면 캐시가 저절로 갈리는 것을 함께 보인다.
# 전제: docker compose up (api:8080, worker:8081, ner:8100, redis, postgres), 루트 .env에 키.
# LLM 호출: 총 1회 (2번째 요청부터는 캐시가 막는다 — 그게 이 데모의 내용이다).
set -euo pipefail
cd "$(dirname "$0")/.."
API=localhost:8080
PSQL="docker exec sjw-postgres psql -U sjw -d sjw -t -A -c"
TEXT='傳于李馨長曰知道'

jobid() { python3 -c "import json,sys; print(json.load(sys.stdin)['jobId'])"; }
wait_done() {
  for _ in $(seq 1 60); do
    S=$($PSQL "SELECT status FROM translation_job WHERE id='$1'")
    case "$S" in SUCCEEDED|DEAD|FAILED) echo "$S"; return;; esac
    sleep 2
  done
  echo TIMEOUT
}
view() { curl -s $API/api/v1/translations/"$1"; }

echo "== 0) 파이프라인 버전 (이 조합이 캐시를 가른다)"
echo "   NER: $(curl -s localhost:8100/healthz)"

# 데모는 미스→히트 전이를 보여주는 것이므로 이 문장의 엔트리만 비우고 시작한다.
# (전체 flush가 아니다 — 다른 문장의 캐시는 건드리지 않는다)
HASH=$(python3 -c "import hashlib,re,sys,unicodedata; t=re.sub(r'\s+','',unicodedata.normalize('NFC',sys.argv[1])); print(hashlib.sha256(t.encode()).hexdigest())" "$TEXT")
STALE=$(docker exec sjw-redis redis-cli --scan --pattern "cache:l1:*:$HASH" || true)
if [ -n "$STALE" ]; then
  echo "$STALE" | while read -r k; do docker exec sjw-redis redis-cli DEL "$k" > /dev/null; done
  echo "   이 문장의 기존 캐시 항목 $(echo "$STALE" | wc -l | tr -d ' ')건 제거 (데모 재현성)"
fi

echo
echo "== 1) 첫 요청 — 캐시 미스, LLM 호출 1회"
J1=$(curl -s -X POST $API/api/v1/translations -H 'Content-Type: application/json' \
  -H "Idempotency-Key: cache-demo-$(date +%s)-a" -d "{\"text\":\"$TEXT\",\"year\":1623}" | jobid)
echo "   job=$J1 status=$(wait_done "$J1")"
view "$J1" | python3 -m json.tool

echo
echo "== 2) 같은 문장 재요청 — 멱등키를 다르게 준다 (멱등이 아니라 캐시로 막히는 것을 보이려고)"
J2=$(curl -s -X POST $API/api/v1/translations -H 'Content-Type: application/json' \
  -H "Idempotency-Key: cache-demo-$(date +%s)-b" -d "{\"text\":\"$TEXT\",\"year\":1623}" | jobid)
echo "   job=$J2 status=$(wait_done "$J2")"
view "$J2" | python3 -m json.tool

echo
echo "== 3) 증명: job 2건 / LLM 호출 원장 1건"
$PSQL "SELECT id, cache_hit_level, quality_grade, model_used, tokens_in
         FROM translation_job WHERE id IN ('$J1','$J2') ORDER BY created_at"
LEDGER=$($PSQL "SELECT count(*) FROM cost_ledger WHERE job_id IN ('$J1','$J2')")
echo "   cost_ledger 행: $LEDGER (기대: 1)"
[ "$LEDGER" = "1" ] || { echo "   !! 절감이 증명되지 않았다"; exit 1; }

echo
echo "== 4) 동기 경로도 같은 캐시를 쓴다 (meta.cacheHit, latencyMs)"
curl -s -X POST $API/api/v1/translations/sync -H 'Content-Type: application/json' \
  -d "{\"text\":\"$TEXT\",\"year\":1623}" \
  | python3 -c "import json,sys; m=json.load(sys.stdin)['meta']; print('   cacheHit=%s model=%s tokensIn=%s latency=%s' % (m['cacheHit'], m['model'], m['tokensIn'], m['latencyMs']))"

echo
echo "== 5) 메트릭 (§9.1) — 비동기 경로는 worker, 동기 경로는 api가 센다"
# NOTE: /actuator/prometheus는 아직 404다 (micrometer-registry-prometheus 미도입 —
#       Grafana 대시보드를 세우는 M5의 일). 카운터 자체는 actuator/metrics로 확인된다.
counter() {
  curl -s "$1/actuator/metrics/$2" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['measurements'][0]['value'])" 2>/dev/null \
    || echo "0 (없음)"
}
echo "   worker translation.cache.hit  = $(counter localhost:8081 translation.cache.hit)"
echo "   worker translation.cache.miss = $(counter localhost:8081 translation.cache.miss)"
echo "   api    translation.cache.hit  = $(counter localhost:8080 translation.cache.hit)"

echo
echo "== 6) 무효화: 키를 이루는 축이 바뀌면 히트가 사라진다"
KEYS=$(docker exec sjw-redis redis-cli --scan --pattern 'cache:l1:*')
echo "   현재 키 (버전 세그먼트가 눈으로 보인다 — kb:prompt:ner:epoch:원문해시):"
echo "$KEYS" | sed 's/^/     /'
cat <<'TXT'
   축을 바꿔 재기동하면 같은 문장이 다시 미스가 된다 (각각 LLM 1회 소모):
     NER_MODE=rule  docker compose -f deploy/docker-compose.yml up -d api worker   # NER 모델 교체
     KB_NAME=jeongjo docker compose -f deploy/docker-compose.yml up -d api worker  # 인물 사전 교체
     CACHE_EPOCH=2  docker compose -f deploy/docker-compose.yml up -d api worker   # 번역 LLM 교체용 수동 손잡이
   되돌리면 옛 엔트리가 그대로 히트한다 — 무효화는 파괴가 아니라 키 공간 분리다.
TXT
