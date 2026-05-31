"""SillokBert-NER로 eval_set_1925 원문 개체명 태깅"""
import json
from transformers import pipeline
from collections import Counter, defaultdict
from tqdm import tqdm

EVAL_FILE = "eval_assets/eval_set_1925.json"
OUT_FILE  = "eval_assets/ner_results.jsonl"
STAT_FILE = "eval_assets/ner_stats.txt"

print("모델 로딩 중: ddokbaro/SillokBert-NER")
ner = pipeline(
    "token-classification",
    model="ddokbaro/SillokBert-NER",
    aggregation_strategy="simple",
    device=-1,  # CPU
)

corpus = json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]
print(f"eval set: {len(corpus)}개\n")

tag_counter = Counter()
entity_counter = defaultdict(Counter)  # tag -> entity text -> count

results = []
with open(OUT_FILE, "w", encoding="utf-8") as out_f:
    for entry in tqdm(corpus, desc="NER 태깅"):
        text = entry["original"]
        try:
            entities = ner(text)
        except Exception as e:
            entities = []

        tagged = []
        for ent in entities:
            tag  = ent["entity_group"]
            word = ent["word"]
            score= round(ent["score"], 3)
            tagged.append({"tag": tag, "word": word, "score": score})
            tag_counter[tag] += 1
            entity_counter[tag][word] += 1

        row = {"id": entry["id"], "original": text, "entities": tagged}
        out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
        results.append(row)

# 통계 출력 및 저장
lines = []
lines.append(f"NER 결과 통계 (eval_set_1925, n={len(corpus)})\n")
lines.append(f"{'='*60}\n")

lines.append("태그별 총 빈도:")
for tag, cnt in tag_counter.most_common():
    lines.append(f"  {tag:6s} {cnt:6d}개")

lines.append("")
for tag in ["PER", "LOC", "POH", "DAT"]:
    top = entity_counter[tag].most_common(20)
    if not top:
        continue
    lines.append(f"\n[{tag}] 상위 20개:")
    for word, cnt in top:
        lines.append(f"  {cnt:4d}  {word}")

# 개체명이 없는 항목 수
no_entity = sum(1 for r in results if not r["entities"])
lines.append(f"\n개체명 없는 항목: {no_entity}개 ({no_entity/len(corpus)*100:.1f}%)")

for l in lines:
    print(l)

with open(STAT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\n저장: {OUT_FILE}")
print(f"저장: {STAT_FILE}")
