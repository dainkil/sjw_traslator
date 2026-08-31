#!/usr/bin/env python3
"""ONNX 변환 전후 NER 지연·정확도 비교 (M1 수용 기준).

비교 대상: PyTorch(기준) / ONNX fp32 / ONNX INT8
데이터: eval/eval300_1925.json 원문 중 무작위 N건 (seed=42)
지표:
  - 지연: mean / p50 / p95 (단건, CPU)
  - 정확도: PyTorch 기준 대비 엔티티 완전일치율(surface+type),
            ner_groundtruth_300 대비 PER surface recall

사용: uv run python scripts/benchmark.py [--n 100]
"""
import argparse
import json
import random
import statistics as st
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent


def pct(xs, p):
    return sorted(xs)[min(int(len(xs) * p), len(xs) - 1)]


def torch_predict_fn():
    from transformers import pipeline
    pipe = pipeline("ner", model="ddokbaro/SillokBert-NER",
                    aggregation_strategy="simple", device=-1)

    def predict(text):
        return [{"surface": r["word"].replace(" ", ""), "type": r["entity_group"],
                 "score": float(r["score"])} for r in pipe(text) if r["score"] > 0.5]
    return predict


def onnx_predict_fn(model_dir):
    import sys
    sys.path.insert(0, str(ROOT))
    from app.ner import NerModel
    m = NerModel(model_dir)
    return lambda text: m.predict(text, min_score=0.5)


def bench(name, fn, texts):
    lat = []
    results = []
    for t in texts:
        t0 = time.perf_counter()
        results.append(fn(t))
        lat.append((time.perf_counter() - t0) * 1000)
    print(f"{name:12s} mean {st.mean(lat):8.1f}ms | p50 {pct(lat, 0.5):8.1f}ms | "
          f"p95 {pct(lat, 0.95):8.1f}ms")
    return results, lat


def entity_set(res):
    return {(e["surface"], e["type"]) for e in res}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()

    corpus = json.loads((REPO / "eval" / "eval300_1925.json").read_text())["corpus"]
    gt = json.loads((REPO / "eval" / "ner_groundtruth_300.json").read_text())
    random.seed(42)
    sample = random.sample(corpus, min(args.n, len(corpus)))
    texts = [c["original"] for c in sample]

    print(f"# 벤치마크: {len(texts)}문장 (seed=42), CPU 단건 추론\n")
    torch_res, _ = bench("PyTorch", torch_predict_fn(), texts)
    fp32_res, _ = bench("ONNX fp32", onnx_predict_fn(ROOT / "models" / "onnx-fp32"), texts)
    int8_res, _ = bench("ONNX INT8", onnx_predict_fn(ROOT / "models" / "onnx-int8"), texts)

    for name, res in [("ONNX fp32", fp32_res), ("ONNX INT8", int8_res)]:
        agree = sum(entity_set(a) == entity_set(b) for a, b in zip(torch_res, res))
        print(f"\n{name} vs PyTorch: 문장 단위 엔티티 완전일치 {agree}/{len(texts)} "
              f"({agree / len(texts):.1%})")

    # 골든셋 PER recall (모델별)
    print()
    for name, res in [("PyTorch", torch_res), ("ONNX fp32", fp32_res), ("ONNX INT8", int8_res)]:
        hit = tot = 0
        for c, r in zip(sample, res):
            gold = {h for t, h, _ in gt.get(c["id"], []) if t == "PER"}
            pred = {e["surface"] for e in r if e["type"] == "PER"}
            tot += len(gold)
            hit += len(gold & pred)
        print(f"{name:12s} 골든셋 PER recall: {hit}/{tot} ({hit / tot:.1%})" if tot else "no gold")


if __name__ == "__main__":
    main()
