"""원문 / 정답 / gemma baseline / gemma few-shot 비교 파일 생성"""
import json, re

EVAL_FILE     = "eval_assets/eval_set_1925.json"
BASELINE_FILE = "bleu_results_gemma4_26b.jsonl"
FEWSHOT_FILE  = "eval_assets/results_fewshot_gemma.jsonl"
OUT_FILE      = "eval_assets/comparison_fewshot_vs_baseline.txt"

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

# 1. eval_set 로드
corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}

# 2. baseline 로드
baseline = {}
with open(BASELINE_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("id") in corpus and "hypothesis" in r:
            baseline[r["id"]] = strip(r["hypothesis"])

# 3. fewshot 로드
fewshot = {}
with open(FEWSHOT_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("id") in corpus and "hypothesis" in r:
            fewshot[r["id"]] = strip(r["hypothesis"])

# 4. 교집합 ID
ids = [eid for eid in corpus if eid in baseline and eid in fewshot]
print(f"교집합 항목: {len(ids)}개")

SEP = "=" * 80

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(f"Gemma few-shot vs baseline 번역 비교\n")
    f.write(f"항목 수: {len(ids)}\n\n")
    for i, eid in enumerate(ids, 1):
        e = corpus[eid]
        f.write(f"{SEP}\n")
        f.write(f"[{i:04d}] ID: {eid}  날짜: {e.get('date','')}\n")
        f.write(f"{'─'*80}\n")
        f.write(f"[원문]     {e['original']}\n")
        f.write(f"[정답]     {e['reference']}\n")
        f.write(f"[baseline] {baseline[eid]}\n")
        f.write(f"[few-shot] {fewshot[eid]}\n\n")

print(f"저장: {OUT_FILE}")
