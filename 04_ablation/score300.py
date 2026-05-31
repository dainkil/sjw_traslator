"""
3-way Ablation 채점: baseline / few-shot / v4
실행: ablation5way/ 폴더 안에서 python score300.py
"""
import json, re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
from sacrebleu.metrics import BLEU, CHRF
from kiwipiepy import Kiwi
from tqdm import tqdm

BASE = Path(__file__).parent

EVAL_FILE = BASE / "eval300_1925.json"
CONDITIONS = {
    "baseline":  BASE / "results300_baseline.jsonl",
    "few-shot":  BASE / "results300_fewshot.jsonl",
    "v4":        BASE / "results300_v4.jsonl",
    "kb-inject": BASE / "results300_kbinject.jsonl",
}
OUTPUT_TXT = BASE / "ablation_300_result.txt"


def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text).strip()
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def load_results(path):
    results = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if "hypothesis" in r:
                        results[r["id"]] = strip(r["hypothesis"])
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return results


loaded = {cond: load_results(path) for cond, path in CONDITIONS.items()}

data = json.load(open(EVAL_FILE, encoding="utf-8"))
eval_ids = data["ids"]
ref_map = {e["id"]: e["reference"] for e in data["corpus"]}

common_ids = [eid for eid in eval_ids
              if all(eid in loaded[c] for c in CONDITIONS) and eid in ref_map]
refs = [ref_map[eid] for eid in common_ids]

print(f"공통 완료 n={len(common_ids)} / 300")
if len(common_ids) < 50:
    print("⚠️  50개 미만 — 번역 더 필요")
    sys.exit(0)

print("형태소 분석 중...")
kiwi = Kiwi()
refs_m = [" ".join(t.form for t in kiwi.tokenize(r)) for r in tqdm(refs, desc="ref", leave=False)]

results_table = {}
for cond in CONDITIONS:
    hyps = [loaded[cond][eid] for eid in common_ids]
    bleu_c = BLEU(tokenize="char", effective_order=True).corpus_score(hyps, [refs]).score
    chrf_c = CHRF().corpus_score(hyps, [refs]).score
    hyps_m = [" ".join(t.form for t in kiwi.tokenize(h)) for h in tqdm(hyps, desc=cond, leave=False)]
    bleu_m = BLEU(tokenize="none", effective_order=True).corpus_score(hyps_m, [refs_m]).score
    chrf_m = CHRF().corpus_score(hyps_m, [refs_m]).score
    results_table[cond] = (bleu_c, chrf_c, bleu_m, chrf_m)

W = 90
b0 = results_table["baseline"]
lines = [
    "=" * W,
    f"3-way Ablation (eval300 from eval_set_1925) | n={len(common_ids)}",
    "=" * W,
    f"{'':20s}  {'BLEU(c)':>10}  {'chrF(c)':>10}  {'BLEU(m)':>10}  {'chrF(m)':>10}",
    "─" * W,
]
for cond, (bc, cc, bm, cm) in results_table.items():
    lines.append(f"  {cond:18s}  {bc:>10.2f}  {cc:>10.2f}  {bm:>10.2f}  {cm:>10.2f}")
lines.append("─" * W)
for cond in ["few-shot", "v4"]:
    bc, cc, bm, cm = results_table[cond]
    lines.append(f"  Δ {cond:16s}  {bc-b0[0]:>+10.2f}  {cc-b0[1]:>+10.2f}  {bm-b0[2]:>+10.2f}  {cm-b0[3]:>+10.2f}")
lines.append("=" * W)

output = "\n".join(lines)
print("\n" + output)
with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
    f.write(output + "\n")
print(f"\n저장: {OUTPUT_TXT}")
