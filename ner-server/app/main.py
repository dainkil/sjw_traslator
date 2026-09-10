"""SillokBERT-NER 추론 서버.

실행: uv run uvicorn app.main:app --port 8100
모델: models/onnx-int8 (기본). 환경변수 NER_MODEL_DIR로 교체 가능 (fp32 비교 실측용).
"""
import os
import time
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.ner import NerModel

MODEL_DIR = Path(os.environ.get(
    "NER_MODEL_DIR", Path(__file__).resolve().parent.parent / "models" / "onnx-int8"
))

app = FastAPI(title="sjw-ner-server")
model = NerModel(MODEL_DIR)


class NerRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    min_score: float = 0.5


@app.get("/healthz")
def healthz():
    # model_version은 가중치 파생 체크섬 — 클라이언트(M3 캐시)가 이 값을 캐시 키에 넣어
    # 재학습본 교체 시 옛 결과가 계속 서빙되는 것을 막는다.
    return {"status": "ok", "model_dir": str(MODEL_DIR), "model_version": model.version}


@app.post("/v1/ner")
def ner(req: NerRequest):
    t0 = time.perf_counter()
    entities = model.predict(req.text, min_score=req.min_score)
    return {
        "entities": entities,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
