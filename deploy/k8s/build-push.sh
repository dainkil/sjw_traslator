#!/usr/bin/env bash
# 이미지 빌드·푸시 → kustomization 태그 갱신 (§5.0 2). 배포 = 이 결과를 커밋 → ArgoCD 동기화.
#   deploy/k8s/build-push.sh [tag]     # 기본 tag = git short SHA
# 전제: docker login harbor.skala-gj.com -u skala-gj4 --password-stdin   (https:// 없이 — 붙이면 push 401)
#       ner-server/models/onnx-int8 존재 (gitignore — 로컬에서만 빌드 가능)
# 노드가 x86_64라 Apple Silicon에서도 linux/amd64로 교차 빌드한다.
set -euo pipefail
cd "$(dirname "$0")/../.."

REG="${REG:-harbor.skala-gj.com/skala-gj4}"
TAG="${1:-$(git rev-parse --short HEAD)}"
if [[ -z "${1:-}" && -n "$(git status --porcelain -- common api worker ner-server kb deploy/*.Dockerfile)" ]]; then
  echo "경고: 커밋 안 된 변경이 있다 — 태그 $TAG가 이미지 내용과 어긋난다 (명시 태그를 주거나 먼저 커밋)" >&2
fi
[[ -d ner-server/models/onnx-int8 ]] || { echo "ner-server/models/onnx-int8가 없다 (uv run python scripts/export_onnx.py)" >&2; exit 1; }

for svc in api worker ner; do
  echo "== $REG/sjw-$svc:$TAG" >&2
  docker buildx build --platform linux/amd64 -f "deploy/$svc.Dockerfile" -t "$REG/sjw-$svc:$TAG" --push .
done

# kustomization의 세 이미지 태그를 한 번에 — 셋은 항상 같은 커밋에서 나온다
sed -i.bak -E "s/^(    newTag: )[^ ]+(.*)$/\1$TAG\2/" deploy/k8s/kustomization.yaml && rm deploy/k8s/kustomization.yaml.bak
grep -n "newTag" deploy/k8s/kustomization.yaml >&2
echo "다음: git add deploy/k8s/kustomization.yaml && git commit -m 'deploy: $TAG' && git push  → ArgoCD 동기화" >&2
