#!/usr/bin/env python3
"""SillokBERT-NER → ONNX fp32 → INT8 동적 양자화 (ADR-003).

산출물 (ner-server/models/, gitignore 대상):
  models/onnx-fp32/  — optimum export 결과 + 토크나이저
  models/onnx-int8/  — quantize_dynamic 결과 (서빙 기본)
"""
from pathlib import Path

MODEL_ID = "ddokbaro/SillokBert-NER"
BASE = Path(__file__).resolve().parent.parent / "models"


def main():
    from optimum.onnxruntime import ORTModelForTokenClassification
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoTokenizer

    fp32_dir = BASE / "onnx-fp32"
    int8_dir = BASE / "onnx-int8"
    int8_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] {MODEL_ID} 다운로드 + ONNX export → {fp32_dir}")
    model = ORTModelForTokenClassification.from_pretrained(MODEL_ID, export=True)
    model.save_pretrained(fp32_dir)
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    tok.save_pretrained(fp32_dir)

    print(f"[2/3] INT8 동적 양자화 → {int8_dir}")
    quantize_dynamic(fp32_dir / "model.onnx", int8_dir / "model.onnx", weight_type=QuantType.QInt8)
    # 토크나이저·config는 fp32와 동일
    for f in fp32_dir.iterdir():
        if f.name != "model.onnx":
            (int8_dir / f.name).write_bytes(f.read_bytes())

    fp32_mb = (fp32_dir / "model.onnx").stat().st_size / 1e6
    int8_mb = (int8_dir / "model.onnx").stat().st_size / 1e6
    print(f"[3/3] 완료. 모델 크기: fp32 {fp32_mb:.0f}MB → int8 {int8_mb:.0f}MB")


if __name__ == "__main__":
    main()
