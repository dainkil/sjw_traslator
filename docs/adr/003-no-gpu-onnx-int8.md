# ADR-003: GPU 배제 및 ONNX INT8 CPU 서빙 채택

- 상태: 승인 (실측 근거 확보)
- 날짜: 2026-08-31

## 배경

NER(SillokBERT-NER, BERT-base)은 파이프라인에서 유일한 자체 모델 추론이다. GPU 서빙 여부는 인프라 비용의 큰 갈림길이므로 측정 후 결정한다. (계획서 D3)

## 선택지

1. **ONNX Runtime INT8, CPU 서빙**
2. GPU 인스턴스 서빙 (PyTorch/TensorRT)
3. PyTorch CPU 그대로 서빙 (변환 없음)

## 결정

**선택지 1.** 실측 근거 (docs/benchmarks.md, 골든셋 100문장, Apple M5):

| 엔진 | p50 | mean | 골든셋 PER recall | 모델 크기 |
|---|---|---|---|---|
| PyTorch CPU | 17.9ms | 28.9ms | 100% | 709MB |
| ONNX INT8 | **8.3ms** | 14.8ms | **100%** | **178MB** |

- 계획 단계 가정(100~300ms)보다 두 자릿수 빠른 **한 자릿수 ms**로 실측됐다. E2E 실측 결과 외부 LLM이 전체 p95의 **99.7~99.9%** (docs/benchmarks.md) — NER을 GPU로 더 줄여도 체감 개선은 0에 수렴한다.
- INT8은 PyTorch 대비 문장 단위 엔티티 완전일치 97%지만, 파이프라인이 소비하는 신호(PER 표층형 검출)는 골든셋 recall 100%로 동일 — 품질 손실 없이 메모리 4분의 1.

## 버린 대안과 그 이유

- **GPU(2)**: 추론이 요청당 ~15ms인 워크로드에 GPU 인스턴스 비용(월 수십만 원)을 붙일 근거가 없다. 배치에서도 병목은 LLM API quota이지 NER 처리량이 아니다. "측정했고 그래서 안 썼다"가 이 프로젝트의 서사다.
- **PyTorch CPU(3)**: 동작은 하지만 INT8 대비 2배 느리고 메모리 4배. 변환 비용은 스크립트 1개(`ner-server/scripts/export_onnx.py`)로 일회성이며, 정확도 검증 절차(benchmark.py)까지 갖췄으므로 변환하지 않을 이유가 없다.

## 재검토 조건

- NER 서버로 초당 수백 문장 이상이 몰려 CPU 스케일아웃 비용이 GPU 1대 비용을 넘는 것으로 실측되면 재검토 (M2 배치 실측에서 확인).
