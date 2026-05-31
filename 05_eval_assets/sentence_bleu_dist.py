"""각 문장별 BLEU 계산 후 분포 분석 (baseline vs few-shot)"""
import json, re
from sacrebleu.metrics import BLEU

EVAL_FILE     = "eval_assets/eval_set_1925.json"
BASELINE_FILE = "bleu_results_gemma4_26b.jsonl"
FEWSHOT_FILE  = "eval_assets/results_fewshot_gemma.jsonl"

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}

baseline = {}
with open(BASELINE_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("id") in corpus and "hypothesis" in r:
            baseline[r["id"]] = strip(r["hypothesis"])

fewshot = {}
with open(FEWSHOT_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("id") in corpus and "hypothesis" in r:
            fewshot[r["id"]] = strip(r["hypothesis"])

ids = [eid for eid in corpus if eid in baseline and eid in fewshot]
print(f"항목: {len(ids)}개\n")

bleu_fn = BLEU(tokenize="char", effective_order=True)

results = []
for eid in ids:
    ref = corpus[eid]["reference"]
    b_score = bleu_fn.sentence_score(baseline[eid], [ref]).score
    f_score = bleu_fn.sentence_score(fewshot[eid],  [ref]).score
    results.append({"id": eid, "baseline": b_score, "fewshot": f_score, "diff": f_score - b_score})

# 저장
with open("eval_assets/sentence_bleu_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

b_scores = [r["baseline"] for r in results]
f_scores = [r["fewshot"]  for r in results]
diffs    = [r["diff"]     for r in results]

def stats(arr, name):
    arr_s = sorted(arr)
    n = len(arr)
    mean = sum(arr) / n
    variance = sum((x - mean)**2 for x in arr) / n
    std = variance ** 0.5
    print(f"{name}:")
    print(f"  mean={mean:.2f}  std={std:.2f}  min={arr_s[0]:.2f}  "
          f"p25={arr_s[n//4]:.2f}  median={arr_s[n//2]:.2f}  "
          f"p75={arr_s[3*n//4]:.2f}  max={arr_s[-1]:.2f}")

stats(b_scores, "baseline")
stats(f_scores, "few-shot")
stats(diffs,    "diff (few-shot - baseline)")

# 구간별 분포
bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 101]
labels = ["0-9","10-19","20-29","30-39","40-49","50-59","60-69","70-79","80-89","90-100"]
print("\n구간별 분포 (baseline | few-shot):")
print(f"  {'구간':>8}  {'baseline':>9}  {'few-shot':>9}")
for i in range(len(labels)):
    lo, hi = bins[i], bins[i+1]
    bc = sum(1 for s in b_scores if lo <= s < hi)
    fc = sum(1 for s in f_scores if lo <= s < hi)
    bar_b = "#" * (bc // 5)
    bar_f = "#" * (fc // 5)
    print(f"  {labels[i]:>8}  {bc:>4} {bar_b:<15}  {fc:>4} {bar_f}")

# few-shot이 더 나쁜 케이스
worse = [r for r in results if r["diff"] < -10]
better = [r for r in results if r["diff"] > 20]
print(f"\nfew-shot이 baseline보다 10점+ 낮은 케이스: {len(worse)}개")
print(f"few-shot이 baseline보다 20점+ 높은 케이스: {len(better)}개")
print("저장: eval_assets/sentence_bleu_results.json")
