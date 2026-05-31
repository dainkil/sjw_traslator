import json, re, statistics
from sacrebleu.metrics import BLEU

def strip_thinking(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()

bleu = BLEU(tokenize="char", effective_order=True)

scores = []
with open("bleu_results_gemma4_26b.jsonl", encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if "hypothesis" in r and "reference" in r:
            hyp = strip_thinking(r["hypothesis"])
            ref = r["reference"]
            scores.append(bleu.sentence_score(hyp, [ref]).score)

scores.sort()
n = len(scores)
mean = statistics.mean(scores)
std  = statistics.stdev(scores)
med  = statistics.median(scores)

pcts = [5, 10, 25, 50, 75, 90, 95]
pct_vals = {p: scores[int(p/100 * n)] for p in pcts}

# IQR 기반 이상치
q1 = scores[int(0.25 * n)]
q3 = scores[int(0.75 * n)]
iqr = q3 - q1
lower_iqr = q1 - 1.5 * iqr

# Z-score 기반 (mean - 2*std)
lower_z2 = mean - 2 * std
lower_z3 = mean - 3 * std

print(f"n={n}")
print(f"mean={mean:.2f}  std={std:.2f}  median={med:.2f}")
print(f"min={scores[0]:.2f}  max={scores[-1]:.2f}")
print()
print("퍼센타일:")
for p, v in pct_vals.items():
    print(f"  P{p:>2}: {v:.2f}")
print()
print("이상치 기준별 제거 비율:")
for label, thr in [("IQR(Q1-1.5*IQR)", lower_iqr),
                    ("mean-2std",       lower_z2),
                    ("mean-3std",       lower_z3),
                    ("BLEU<10",         10),
                    ("BLEU<20",         20),
                    ("BLEU<30",         30)]:
    removed = sum(1 for s in scores if s < thr)
    kept = n - removed
    print(f"  {label:<20} thr={thr:>6.2f}  제거={removed:>4}({removed/n*100:.1f}%)  잔류={kept}")

print()
print("구간 분포:")
bins = [(0,10),(10,20),(20,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,90),(90,101)]
for lo, hi in bins:
    cnt = sum(1 for s in scores if lo <= s < hi)
    bar = "#" * (cnt // 10)
    print(f"  {lo:>3}-{hi:<3}: {cnt:>4} {bar}")
