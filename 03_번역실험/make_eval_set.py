import json, re, random, statistics
from sacrebleu.metrics import BLEU
from collections import Counter

def strip_thinking(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()

# 원본 3000개 샘플 (seed=42 고정)
data = json.load(open("Merged_Corpus_Final.json", encoding="utf-8"))
corpus = data["corpus"]
random.seed(42)
sample = random.sample(corpus, 3000)
id_to_entry = {e["id"]: e for e in sample}

# Gemma 문장 단위 BLEU 계산
bleu = BLEU(tokenize="char", effective_order=True)
rows = []
with open("bleu_results_gemma4_26b.jsonl", encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if "hypothesis" in r and "reference" in r:
            hyp = strip_thinking(r["hypothesis"])
            ref = r["reference"]
            score = bleu.sentence_score(hyp, [ref]).score
            entry = id_to_entry.get(r["id"], {})
            rows.append({
                "id": r["id"],
                "date": entry.get("date", ""),
                "original": entry.get("original", ""),
                "reference": ref,
                "_gemma_bleu": round(score, 4),
            })

# 중복 제거 (reference 기준, 점수 높은 것 우선)
rows.sort(key=lambda x: -x["_gemma_bleu"])
seen_refs = set()
dedup = []
for r in rows:
    if r["reference"] not in seen_refs:
        seen_refs.add(r["reference"])
        dedup.append(r)

# thr >= 20 필터
eval_set = [r for r in dedup if r["_gemma_bleu"] >= 20]

scores = [r["_gemma_bleu"] for r in eval_set]
print(f"eval set: {len(eval_set)}개")
print(f"gemma_bleu  mean={statistics.mean(scores):.2f}  median={statistics.median(scores):.2f}  min={min(scores):.2f}")

# gemma 내부 필드 제거 후 저장
clean_set = [{"id": r["id"], "date": r["date"], "original": r["original"], "reference": r["reference"]} for r in eval_set]

out = {"meta": {
    "total": len(clean_set),
    "source": "Merged_Corpus_Final.json",
    "sample_seed": 42,
    "sample_size": 3000,
    "filter": "dedup(reference) + gemma_bleu>=20",
}, "corpus": clean_set}

with open("eval_set_1925.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)


print("저장: eval_set_1925.json")
