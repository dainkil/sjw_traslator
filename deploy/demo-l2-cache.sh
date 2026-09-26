#!/usr/bin/env bash
# L2 템플릿 슬롯 캐시 데모 (M3-S3 수용 근거):
#   ① 구조가 같고 인물만 다른 문장이 LLM 호출 0회로 처리된다 (등급 DEGRADED)
#   ② 재주입 실패가 탐지되어 전체 파이프라인으로 fallback한다 (M3 수용 기준)
#   증명은 cost_ledger — job 2건에 원장 1건. template_hash가 두 job에 같은 값으로 남는다.
#
# 문장: 실제 정형문 '以{인물}爲承旨'(…를 승지로 삼았다)의 인물만 바꾼 쌍.
#   兪榥→유황(받침 O) / 金瑬→김류(받침 X) — 재주입의 조사 보정이 눈에 보인다.
#   셋 다 인조 연간 KB 단일 후보이고 라이브 NER이 PER로 검출한다 (score 0.99).
#
# 전제: CACHE_L2_ENABLED=true 로 기동한 compose 전 스택 + 루트 .env에 키.
#   CACHE_L2_ENABLED=true docker compose -f deploy/docker-compose.yml up -d api worker
# LLM 호출: 총 2회 (문장 A 1회 + fallback 1회 — 나머지는 캐시가 막는다).
set -euo pipefail
cd "$(dirname "$0")/.."
API=localhost:8080
PSQL="docker exec sjw-postgres psql -U sjw -d sjw -t -A -c"
REDIS="docker exec sjw-redis redis-cli"

SRC_A='以兪榥爲承旨'      # 유황  (받침 O)
SRC_B='以金瑬爲承旨'      # 김류  (받침 X) — A와 같은 틀
SRC_C='以姜碩期爲承旨'    # 강석기        — 같은 틀, fallback 확인용
TEMPLATE='以⟪PER1⟫爲承旨'

hash_of() {  # 정규화 해시 (TextHash.normalizedHash와 동일: NFC + 공백 제거 + SHA-256)
  python3 -c "import hashlib,re,sys,unicodedata; t=re.sub(r'\s+','',unicodedata.normalize('NFC',sys.argv[1])); print(hashlib.sha256(t.encode()).hexdigest())" "$1"
}
jobid() { python3 -c "import json,sys; print(json.load(sys.stdin)['jobId'])"; }
submit() {
  curl -s -X POST $API/api/v1/translations -H 'Content-Type: application/json' \
    -H "Idempotency-Key: l2-demo-$(date +%s%N)" -d "{\"text\":\"$1\",\"year\":1623}" | jobid
}
wait_done() {
  for _ in $(seq 1 60); do
    S=$($PSQL "SELECT status FROM translation_job WHERE id='$1'")
    case "$S" in SUCCEEDED|DEAD|FAILED) echo "$S"; return;; esac
    sleep 2
  done
  echo TIMEOUT
}
counter() {
  curl -s "localhost:9081/actuator/metrics/$1${2:+?tag=$2}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['measurements'][0]['value'])" 2>/dev/null \
    || echo 0
}
row() {
  $PSQL "SELECT coalesce(cache_hit_level,'(miss)')||' | '||coalesce(quality_grade,'-')||' | tokens_in='||coalesce(tokens_in::text,'-')||' | tpl='||coalesce(left(template_hash,12),'-') FROM translation_job WHERE id='$1'"
}

echo "== 0) 전제 확인"
L2ON=$(docker exec sjw-worker env 2>/dev/null | grep '^CACHE_L2_ENABLED=' || echo 'CACHE_L2_ENABLED=?')
echo "   worker: $L2ON   (기본값은 false — opt-in이다)"
case "$L2ON" in *=true) ;; *)
  echo "   !! L2가 꺼져 있다. 아래로 다시 띄운 뒤 실행할 것:"
  echo "      CACHE_L2_ENABLED=true docker compose -f deploy/docker-compose.yml up -d api worker"
  exit 1;;
esac
echo "   NER: $(curl -s localhost:8100/healthz)"
TPL_HASH=$(hash_of "$TEMPLATE")
echo "   슬롯화된 원문: $TEMPLATE"
echo "   template_hash: ${TPL_HASH:0:16}…"

echo
echo "== 1) 재현성: 이 세 문장의 L1 엔트리와 이 틀의 L2 엔트리를 비운다 (전체 flush 아님)"
for H in "$(hash_of "$SRC_A")" "$(hash_of "$SRC_B")" "$(hash_of "$SRC_C")"; do
  for K in $($REDIS --scan --pattern "cache:l1:*:$H" || true); do $REDIS DEL "$K" > /dev/null; done
done
L2KEYS=$($REDIS --scan --pattern "cache:l2:*:$TPL_HASH" || true)
for K in $L2KEYS; do $REDIS DEL "$K" > /dev/null; done
echo "   완료"

echo
echo "== 2) 문장 A — 미스. LLM 호출 1회, 번역문이 템플릿화되어 적재된다"
JA=$(submit "$SRC_A"); echo "   job=$JA status=$(wait_done "$JA")"
echo "   $(row "$JA")"
$PSQL "SELECT translated_text FROM translation_result WHERE job_id='$JA'" | sed 's/^/   번역: /'
echo "   적재된 L2 템플릿:"
for K in $($REDIS --scan --pattern "cache:l2:*:$TPL_HASH"); do
  echo "     키   $K"
  $REDIS GET "$K" | python3 -c "import json,sys; d=json.load(sys.stdin); print('     값   template=%r slots=%d model=%s' % (d['translationTemplate'], d['slotCount'], d['producedModel']))"
done

echo
echo "== 3) 문장 B — 같은 틀, 다른 인물. LLM 호출 0회로 인명만 교체된다"
HIT0=$(counter translation.cache.hit 'level:L2')
JB=$(submit "$SRC_B"); echo "   job=$JB status=$(wait_done "$JB")"
echo "   $(row "$JB")"
$PSQL "SELECT translated_text FROM translation_result WHERE job_id='$JB'" | sed 's/^/   번역: /'
echo "   translation.cache.hit{level=L2}: $HIT0 → $(counter translation.cache.hit 'level:L2')"

echo
echo "== 4) 증명: job 2건 / LLM 호출 원장 1건 / 같은 template_hash"
$PSQL "SELECT id, cache_hit_level, quality_grade, tokens_in, left(template_hash,12)
         FROM translation_job WHERE id IN ('$JA','$JB') ORDER BY created_at"
LEDGER=$($PSQL "SELECT count(*) FROM cost_ledger WHERE job_id IN ('$JA','$JB')")
echo "   cost_ledger 행: $LEDGER (기대: 1)"
[ "$LEDGER" = "1" ] || { echo "   !! 절감이 증명되지 않았다"; exit 1; }
GRADE=$($PSQL "SELECT quality_grade FROM translation_job WHERE id='$JB'")
[ "$GRADE" = "DEGRADED" ] || { echo "   !! L2 히트 등급이 DEGRADED가 아니다: $GRADE (ADR-009 위반)"; exit 1; }
echo "   ✅ LLM 호출 0회로 서빙 + 등급 DEGRADED (LLM이 생성하지 않은 문장이므로)"

echo
echo "== 5) 재주입 실패 → fallback (M3 수용 기준). 템플릿에서 마커를 지워 고장을 주입한다"
ABORT0=$(counter translation.cache.reinject.abort 'reason:structure_mismatch')
for K in $($REDIS --scan --pattern "cache:l2:*:$TPL_HASH"); do
  $REDIS SET "$K" '{"translationTemplate":"마커가 사라진 번역문.","producedModel":"broken","slotCount":1,"storedAt":"t"}' > /dev/null
done
echo "   주입 완료 — 이제 문장 C는 마커를 못 찾는다"
JC=$(submit "$SRC_C"); echo "   job=$JC status=$(wait_done "$JC")"
echo "   $(row "$JC")"
$PSQL "SELECT translated_text FROM translation_result WHERE job_id='$JC'" | sed 's/^/   번역: /'
echo "   translation.cache.reinject.abort{structure_mismatch}: $ABORT0 → $(counter translation.cache.reinject.abort 'reason:structure_mismatch')"
CHIT=$($PSQL "SELECT coalesce(cache_hit_level,'MISS') FROM translation_job WHERE id='$JC'")
CLED=$($PSQL "SELECT count(*) FROM cost_ledger WHERE job_id='$JC'")
[ "$CHIT" = "MISS" ] && [ "$CLED" = "1" ] || {
  echo "   !! fallback이 증명되지 않았다 (cache_hit_level=$CHIT, 원장 $CLED행)"; exit 1; }
echo "   ✅ 히트 취소 → 전체 파이프라인 재실행 (원장 1행). 깨진 템플릿을 서빙하지 않았다"

echo
echo "== 6) 무효화는 L1과 같은 방식이다 — 키에 파이프라인 버전이 들어 있다"
$REDIS --scan --pattern 'cache:l2:*' | sed 's/^/   /'
cat <<'TXT'
   축(kb·prompt·ner·epoch)을 바꿔 재기동하면 이 틀도 함께 갈린다 — 무효화 코드 0줄 (ADR-009).
   L2를 끄면(CACHE_L2_ENABLED=false) 히트는 즉시 멈춘다. L1로 승격 적재하지 않기 때문에
   "껐는데도 예전 재주입 결과가 계속 나가는" 상태가 생기지 않는다.
TXT
