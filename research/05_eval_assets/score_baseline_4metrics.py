"""baseline (no few-shot) 4개 지표 계산 — eval_set_1925 ID 기준 필터링"""
import json, re
from sacrebleu.metrics import BLEU, CHRF
from kiwipiepy import Kiwi
from tqdm import tqdm

BASELINE_FILE = "bleu_results_gemma4_26b.jsonl"
EVAL_FILE     = "eval_assets/eval_set_1925.json"

def strip_thinking(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

# eval_set IDs
eval_ids = {e["id"] for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}

hyps, refs = [], []
with open(BASELINE_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("id") in eval_ids and "hypothesis" in r and "reference" in r:
            hyps.append(strip_thinking(r["hypothesis"]))
            refs.append(r["reference"])

print(f"baseline 샘플 (eval_set 교집합): {len(hyps)}")

bleu_c = BLEU(tokenize="char", effective_order=True).corpus_score(hyps, [refs]).score
chrf_c = CHRF().corpus_score(hyps, [refs]).score

print("형태소 분석 중...")
kiwi = Kiwi()
hyps_m = [" ".join(t.form for t in kiwi.tokenize(h)) for h in tqdm(hyps, desc="hyp", leave=False)]
refs_m  = [" ".join(t.form for t in kiwi.tokenize(r)) for r in tqdm(refs,  desc="ref", leave=False)]
bleu_m = BLEU(tokenize="none", effective_order=True).corpus_score(hyps_m, [refs_m]).score
chrf_m = CHRF().corpus_score(hyps_m, [refs_m]).score

print(f"\n{'='*55}")
print(f"baseline (no few-shot) - n={len(hyps)}")
print(f"{'─'*55}")
print(f"BLEU (char):    {bleu_c:.2f}")
print(f"chrF++ (char):  {chrf_c:.2f}")
print(f"BLEU (morph):   {bleu_m:.2f}")
print(f"chrF++ (morph): {chrf_m:.2f}")
print(f"{'='*55}")

with open("eval_assets/baseline_4metrics.json", "w", encoding="utf-8") as f:
    json.dump({"n": len(hyps), "bleu_c": bleu_c, "chrf_c": chrf_c,
               "bleu_m": bleu_m, "chrf_m": chrf_m}, f, indent=2)
print("저장: eval_assets/baseline_4metrics.json")
