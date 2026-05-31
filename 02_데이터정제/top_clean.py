import json, re
from sacrebleu.metrics import BLEU

def strip_thinking(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()

bleu = BLEU(tokenize="char", effective_order=True)

rows = []
with open("bleu_results_gemma4_26b.jsonl", encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if "hypothesis" in r and "reference" in r:
            hyp = strip_thinking(r["hypothesis"])
            ref = r["reference"]
            score = bleu.sentence_score(hyp, [ref]).score
            rows.append({"id": r["id"], "score": score, "hypothesis": hyp, "reference": ref})

rows.sort(key=lambda x: x["score"], reverse=True)

print(f"전체: {len(rows)}개")
for n in [100, 500, 1000, 2000]:
    top = rows[:n]
    avg = sum(r["score"] for r in top) / n
    mn = top[-1]["score"]
    print(f"상위 {n:>4}개  평균: {avg:.2f}  최솟값: {mn:.2f}")
