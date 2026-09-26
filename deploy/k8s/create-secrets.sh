#!/usr/bin/env bash
# sjw-secrets 생성 (§5.0 3) — git·ArgoCD 밖. 값은 저장소 루트 .env에서 읽는다:
#   GEMINI_API_KEY (필수, 운영자 테넌트 배치용 — 결제 미연동 프로젝트의 키, ADR-016)
#   POSTGRES_PASSWORD / REDIS_PASSWORD (없으면 랜덤 생성 — 생성값은 출력하지 않는다)
#
# 이미 있으면 덮어쓰지 않는다: postgres 비밀번호는 PVC 최초 초기화 때만 적용되므로, 바꾸면 DB 접속이 끊긴다.
# 정말 교체하려면 --replace (postgres는 볼륨을 새로 만들 때만).
#
# Harbor pull secret은 별도로, 사용자가 직접 (비밀번호가 명령 기록에 남지 않게 --password-stdin 경로로 로그인한 뒤):
#   kubectl create secret docker-registry harbor-cred --docker-server=harbor.skala-gj.com \
#     --docker-username=skala-gj4 --docker-password="$(read -rs p; echo "$p")"
set -euo pipefail
cd "$(dirname "$0")/../.."

NS="${NS:-skala-gj4}"
if kubectl -n "$NS" get secret sjw-secrets >/dev/null 2>&1 && [[ "${1:-}" != "--replace" ]]; then
  echo "sjw-secrets가 이미 있다 — 그대로 둔다 (교체는 --replace)" >&2
  exit 0
fi

[[ -f .env ]] || { echo ".env가 없다 (cp .env.example .env)" >&2; exit 1; }
val() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

GEMINI_API_KEY="$(val GEMINI_API_KEY)"
[[ -n "$GEMINI_API_KEY" && "$GEMINI_API_KEY" != your-* ]] || { echo ".env의 GEMINI_API_KEY가 비었다" >&2; exit 1; }
POSTGRES_PASSWORD="$(val POSTGRES_PASSWORD)"; POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(openssl rand -hex 20)}"
REDIS_PASSWORD="$(val REDIS_PASSWORD)";       REDIS_PASSWORD="${REDIS_PASSWORD:-$(openssl rand -hex 20)}"

# 값을 명령행 인자로 넘기지 않는다(ps에 보인다) — 권한 600 임시 파일로.
TMP="$(mktemp)"; chmod 600 "$TMP"; trap 'rm -f "$TMP"' EXIT
printf 'GEMINI_API_KEY=%s\nPOSTGRES_PASSWORD=%s\nREDIS_PASSWORD=%s\n' \
  "$GEMINI_API_KEY" "$POSTGRES_PASSWORD" "$REDIS_PASSWORD" > "$TMP"

kubectl -n "$NS" create secret generic sjw-secrets --from-env-file="$TMP" --dry-run=client -o yaml \
  | kubectl -n "$NS" apply -f -
echo "sjw-secrets 적용 완료 (ns=$NS)" >&2
