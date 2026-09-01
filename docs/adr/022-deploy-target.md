# ADR-022: 배포 타겟 및 호스팅 선택 (§15)

- 상태: 승인 (M2.5-S8에서 확정 — M6로 미루지 않는 이유는 §15.2)
- 날짜: 2026-09-01

## 배경

배포 타겟이 미정이면 M6에서 배포 자체가 불가하고(§10 리스크 표), 무엇보다 **ARM 여부가 지금의
컨테이너 이미지 전략을 정한다**: NER 서버가 기동 시 700MB를 내려받는 구조로는 무료 인스턴스
컨테이너화가 성립하지 않아 INT8(174MB)을 이미지에 굽는 결정(S8 Dockerfile)이 선행돼야 했다.
예산은 0원이다 (ADR-016).

## 선택지

1. **Oracle Cloud Always Free (Ampere A1, ARM aarch64 — 4 OCPU / 24GB / 200GB)**
2. Self-host (개인 장비) + `docker compose up` + CI
3. HuggingFace Spaces / 기타 무료 PaaS

## 결정

**A(1) 우선, 계정 확보 실패 시 C(2)로 축소.**

- A1 무료 셰이프는 이 스택(JVM 2개 + ONNX CPU 추론 + Redis + Postgres)에 충분하고 24시간 상시라
  배치·시계열 메트릭(§9.1)이 실제로 쌓인다. 단, 용량 부족으로 프로비저닝이 거부되는 사례가 흔해
  확보를 보장할 수 없다 — 그래서 fallback이 있는 결정이다.
- **ARM 대응은 이미 끝났다**: base 이미지 전부 multi-arch(eclipse-temurin, python-slim, redis, postgres),
  onnxruntime은 aarch64 휠 제공. Dockerfile 수정 없이 ARM에서 빌드된다.
- self-host fallback도 같은 산출물을 쓴다: `docker compose -f deploy/docker-compose.yml up -d --build`
  한 줄이 전 스택이다 (M2.5 수용 기준 5). 잃는 것은 상시성뿐, 재현성은 동일.

## 버린 대안과 그 이유

- **HF Spaces(3)**: 무료 Space는 영구 디스크가 없고 무활동 시 잠든다. Postgres 원장·배치 체크포인트가
  재시작마다 소실되면 M2의 재개·멱등·예산 원장이 전부 무의미해진다. 결정적으로 본인 키 공개 = RPD 20
  즉시 소진 — 호스팅이 아니라 BYOK(ADR-020)로 풀 문제다 (§15.2 원문).
- 기타 무료 PaaS(Fly/Render 등 무료 축소 추세): 상시 프로세스 + 영구 DB + 멀티 컨테이너를 무료로
  주는 곳이 사실상 없다. 조건 변동 리스크에 포폴 마감을 걸 수 없다.

## 재검토 조건

- A1 프로비저닝이 2주 내 확보되지 않으면 즉시 C로 확정하고 M6 계획에서 원격 배포 단계를 제거한다.
- 프로젝트가 실사용(연구자 다수)으로 넘어가면 유료 최소 인스턴스 재평가 — 그때는 ADR-016도 함께 갱신된다.
