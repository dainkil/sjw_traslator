import json
import re
from sacrebleu.metrics import BLEU, CHRF
from tqdm import tqdm
from kiwipiepy import Kiwi

kiwi = Kiwi()

PRECOMPUTED = [
    {"model": "gemma-4-26b",  "n": 2775, "bleu_c": 31.92, "chrf_c": 27.59, "bleu_m": 24.32, "chrf_m": 28.99},
    {"model": "deepseek-v3",  "n": 3000, "bleu_c": 24.99, "chrf_c": 23.29, "bleu_m": 19.12, "chrf_m": 24.40},
]


def strip_thinking(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()


def score_qwen3():
    hyps_raw, refs = [], []
    with open("bleu_results_qwen3_235b.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "hypothesis" in r and "reference" in r:
                hyps_raw.append(strip_thinking(r["hypothesis"]))
                refs.append(r["reference"])

    n = len(hyps_raw)
    print(f"[qwen3-235b] 유효 샘플: {n}개")

    bleu_c = BLEU(tokenize="char", effective_order=True).corpus_score(hyps_raw, [refs]).score
    chrf_c = CHRF().corpus_score(hyps_raw, [refs]).score
    print(f"  BLEU(char): {bleu_c:.2f}  chrF++(char): {chrf_c:.2f}")

    print("  형태소 분석 중...")
    hyps_m = [" ".join(t.form for t in kiwi.tokenize(h)) for h in tqdm(hyps_raw, desc="  hyp", leave=False)]
    refs_m  = [" ".join(t.form for t in kiwi.tokenize(r)) for r in tqdm(refs,     desc="  ref", leave=False)]

    bleu_m = BLEU(tokenize="none", effective_order=True).corpus_score(hyps_m, [refs_m]).score
    chrf_m = CHRF().corpus_score(hyps_m, [refs_m]).score
    print(f"  BLEU(morph): {bleu_m:.2f}  chrF++(morph): {chrf_m:.2f}")

    return {"model": "qwen3-235b", "n": n, "bleu_c": bleu_c, "chrf_c": chrf_c, "bleu_m": bleu_m, "chrf_m": chrf_m}


if __name__ == "__main__":
    results = PRECOMPUTED + [score_qwen3()]

    header  = f"{'모델':<18} {'n':>5} {'BLEU(char)':>10} {'chrF(char)':>10} {'BLEU(morph)':>12} {'chrF(morph)':>12}"
    sep     = "=" * 70
    row_fmt = "{model:<18} {n:>5} {bleu_c:>10.2f} {chrf_c:>10.2f} {bleu_m:>12.2f} {chrf_m:>12.2f}"

    print(f"\n{sep}")
    print(header)
    print("-" * 70)
    for r in results:
        print(row_fmt.format(**r))
    print(sep)

    with open("comparison_all_models.txt", "w", encoding="utf-8") as f:
        f.write(f"{sep}\n{header}\n{'-'*70}\n")
        for r in results:
            f.write(row_fmt.format(**r) + "\n")
        f.write(f"{sep}\n")

    print("\n저장: comparison_all_models.txt")
