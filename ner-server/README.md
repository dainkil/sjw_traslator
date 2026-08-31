# ner-server

SillokBERT-NER(BIO 9태그: PER/POS/LOC/DAT) 추론 전용 서버. ONNX Runtime INT8, CPU (ADR-002, ADR-003).

## 준비 (최초 1회)

```bash
uv sync
uv run python scripts/export_onnx.py   # HF에서 ddokbaro/SillokBert-NER 다운로드 → ONNX fp32 → INT8
```

산출물은 `models/`(gitignore)에 생성된다: `onnx-fp32/`, `onnx-int8/`(서빙 기본).

## 실행

```bash
uv run uvicorn app.main:app --port 8100
```

```
GET  /healthz
POST /v1/ner   {"text": "...", "min_score": 0.5}
  → {"entities": [{"surface","type","start","end","score"}], "latency_ms": ...}
```

`NER_MODEL_DIR` 환경변수로 fp32 모델 지정 가능 (비교 실측용).

## 벤치마크

```bash
uv run python scripts/benchmark.py --n 100
```

결과는 `docs/benchmarks.md`에 기록되어 있다 (INT8: p50 8.3ms, PER recall 100%).
