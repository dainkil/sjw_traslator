# ADR-002: Python NER 서버 프로세스 분리

- 상태: 초안 (M1 구현 시 실측치로 확정)
- 날짜: 2026-08-31

## 배경

NER 모델(SillokBERT-NER, BERT-base, 상주 메모리 ~1GB)은 HuggingFace/PyTorch 생태계에 있고, API/Worker는 JVM(Spring Boot)이다. 계획서 D2.

## 선택지

1. **Python + FastAPI + ONNX Runtime 별도 프로세스** — Worker가 HTTP로 호출.
2. JVM 내 서빙 (DJL / ONNX Runtime Java) — 프로세스 하나로 단순화.
3. Worker마다 Python 사이드카.

## 결정

**선택지 1.** 런타임·메모리 프로파일·스케일 축(요청 수 vs CPU 추론)이 서로 다르므로 분리한다. 합치면 Worker 스케일아웃마다 1GB 모델이 따라 올라간다. 이 분리가 "Spring(오케스트레이션) + Python(추론)" 구조의 당위성 자체다.

## 버린 대안과 그 이유

- (2) DJL/ONNX Java: 기술적으로 가능하나 토크나이저 호환·전처리 재구현 비용이 크고, ONNX 변환 전후 검증 도구가 Python 생태계에 있다. *(M1에서 실측 근거 보강 예정)*
- (3) 사이드카: 스케일 축 분리 실패 — Worker 수 = NER 인스턴스 수로 강제 결합된다.

## 재검토 조건

- NER 호출의 네트워크 오버헤드가 추론 시간 자체를 지배하는 것으로 실측되면 (2) 재검토.
