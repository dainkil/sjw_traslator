#!/usr/bin/env python3
"""M1 단계별 지연 실측 (§2.1 표를 실측치로 교체하기 위한 하네스).

전제: NER 서버(:8100)와 API 서버(:8080)가 떠 있어야 한다.
  cd ner-server && uv run uvicorn app.main:app --port 8100
  cd api && (set -a; source ../.env; set +a; ./gradlew bootRun)

사용: uv run --with httpx python eval/measure_e2e.py [--n 30]
비용: n=30 기준 Gemini 2.5 Flash 호출 30회 (약 $0.03 수준. 실행 전 확인).
"""
import argparse
import json
import random
import statistics as st
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
API = "http://localhost:8080/api/v1/translations/sync"


def reign_year_to_ad(doc_id: str) -> int | None:
    # SJW-A19070xx-... → 인조(A) 19년 → 1623 + 19 - 1
    try:
        if doc_id[4] == "A":
            return 1623 + int(doc_id[5:7]) - 1
    except (IndexError, ValueError):
        pass
    return None


def pct(xs, p):
    return sorted(xs)[min(int(len(xs) * p), len(xs) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    corpus = json.loads((REPO / "eval" / "eval300_1925.json").read_text())["corpus"]
    random.seed(42)
    sample = random.sample(corpus, min(args.n, len(corpus)))

    stages = {}
    tokens_in, tokens_out, client_ms, fails = [], [], [], 0
    with httpx.Client(timeout=120) as client:
        for i, c in enumerate(sample):
            body = {"text": c["original"]}
            year = reign_year_to_ad(c["id"])
            if year:
                body["year"] = year
            t0 = time.perf_counter()
            try:
                r = client.post(API, json=body)
                r.raise_for_status()
            except Exception as e:
                fails += 1
                print(f"  [{i}] 실패: {e}")
                continue
            client_ms.append((time.perf_counter() - t0) * 1000)
            meta = r.json()["meta"]
            for k, v in (meta.get("latencyMs") or {}).items():
                stages.setdefault(k, []).append(v)
            if meta.get("tokensIn"):
                tokens_in.append(meta["tokensIn"])
            if meta.get("tokensOut"):
                tokens_out.append(meta["tokensOut"])
            if (i + 1) % 10 == 0:
                print(f"  {i + 1}/{len(sample)}…")

    n = len(client_ms)
    print(f"\n# E2E 실측: 성공 {n} / 실패 {fails}\n")
    print(f"{'단계':8s} {'mean':>9s} {'p50':>9s} {'p95':>9s}")
    for k in ["ner", "link", "prompt", "llm", "total"]:
        xs = stages.get(k, [])
        if xs:
            print(f"{k:8s} {st.mean(xs):8.1f}ms {pct(xs, 0.5):8.1f}ms {pct(xs, 0.95):8.1f}ms")
    print(f"{'http왕복':8s} {st.mean(client_ms):8.1f}ms {pct(client_ms, 0.5):8.1f}ms "
          f"{pct(client_ms, 0.95):8.1f}ms")

    if stages.get("llm") and stages.get("total"):
        share = sum(stages["llm"]) / sum(stages["total"])
        p95_share = pct(stages["llm"], 0.95) / pct(stages["total"], 0.95)
        print(f"\nLLM 비중: 합계 기준 {share:.1%}, p95 기준 {p95_share:.1%}  ← §2.1 핵심 수치")
    if tokens_in:
        print(f"토큰/요청: in {st.mean(tokens_in):.0f}, out {st.mean(tokens_out):.0f}"
              f"  ← cost_model.py 파라미터 검증용")


if __name__ == "__main__":
    main()
