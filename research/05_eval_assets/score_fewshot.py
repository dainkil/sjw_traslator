"""836개 현재 결과로 few-shot vs baseline BLEU 스코어링"""
import json, re
from sacrebleu.metrics import BLEU, CHRF
from kiwipiepy import Kiwi
from tqdm import tqdm

OUTPUT_FILE = "eval_assets/results_fewshot_gemma.jsonl"
MODEL = "gemma-4-26b-a4b-it"

def strip_thinking(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

hyps, refs = [], []
with open(OUTPUT_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if "hypothesis" in r and "reference" in r:
            hyps.append(strip_thinking(r["hypothesis"]))
            refs.append(r["reference"])

print(f"샘플 수: {len(hyps)}")

bleu_c = BLEU(tokenize="char", effective_order=True).corpus_score(hyps, [refs]).score
chrf_c = CHRF().corpus_score(hyps, [refs]).score

print("형태소 분석 중...")
kiwi = Kiwi()
hyps_m = [" ".join(t.form for t in kiwi.tokenize(h)) for h in tqdm(hyps, desc="hyp", leave=False)]
refs_m  = [" ".join(t.form for t in kiwi.tokenize(r)) for r in tqdm(refs,  desc="ref", leave=False)]
bleu_m = BLEU(tokenize="none", effective_order=True).corpus_score(hyps_m, [refs_m]).score
chrf_m = CHRF().corpus_score(hyps_m, [refs_m]).score

BASE_BLEU_C = 34.98

print(f"\n{'='*55}")
print(f"{'':20} {'few-shot':>12} {'baseline':>12}")
print(f"{'─'*55}")
print(f"{'BLEU (char)':20} {bleu_c:>12.2f} {BASE_BLEU_C:>12.2f}")
print(f"{'chrF++ (char)':20} {chrf_c:>12.2f}")
print(f"{'BLEU (morph)':20} {bleu_m:>12.2f}")
print(f"{'chrF++ (morph)':20} {chrf_m:>12.2f}")
print(f"{'n':20} {len(hyps):>12}")
print(f"{'='*55}")

with open("eval_assets/result_fewshot_vs_baseline.txt", "w", encoding="utf-8") as f:
    f.write(f"모델: {MODEL}\n")
    f.write(f"샘플: {len(hyps)}개 (부분 결과)\n\n")
    f.write(f"{'':20} {'few-shot':>12} {'baseline':>12}\n")
    f.write(f"{'BLEU (char)':20} {bleu_c:>12.2f} {BASE_BLEU_C:>12.2f}\n")
    f.write(f"{'chrF++ (char)':20} {chrf_c:>12.2f}\n")
    f.write(f"{'BLEU (morph)':20} {bleu_m:>12.2f}\n")
    f.write(f"{'chrF++ (morph)':20} {chrf_m:>12.2f}\n")
print("저장: eval_assets/result_fewshot_vs_baseline.txt")
