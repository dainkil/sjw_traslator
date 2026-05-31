"""
eval300 NER 정답지 생성
- 기존 ner_groundtruth.json 재활용 (629개 중 겹치는 것)
- 나머지만 SillokBERT-NER 새로 돌림
- 출력: ablation5way/ner_groundtruth_300.json
"""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
from transformers import pipeline
from tqdm import tqdm
from pathlib import Path

EVAL_FILE     = "ablation5way/eval300_1925.json"
EXISTING_NER  = "ablation5way/ner_groundtruth.json"
MALMOI_MASTER = "말모이/person_master.json"
MALMOI_INDEX  = "말모이/inverted_index_injo.json"
OUT_FILE      = "ablation5way/ner_groundtruth_300.json"

# 말모이 로딩
print("말모이 로딩...")
pm_list = json.load(open(MALMOI_MASTER, encoding="utf-8"))
hanja_map = {}
for p in pm_list:
    h = (p.get("한자_명") or "").strip().lstrip("﻿")
    k = (p.get("한글_명") or "").strip()
    if h and k:
        hanja_map[h] = k
inv = json.load(open(MALMOI_INDEX, encoding="utf-8"))
pm_by_id = {p["인물아이디"]: p for p in pm_list}
for key, ids in inv.items():
    if key not in hanja_map and ids:
        k = pm_by_id.get(ids[0], {}).get("한글_명", "")
        if k:
            hanja_map[key] = k
print(f"한자→한글 매핑: {len(hanja_map)}개")

# 기존 NER 결과 로드
existing = {}
if Path(EXISTING_NER).exists():
    existing = json.load(open(EXISTING_NER, encoding="utf-8"))
    print(f"기존 NER 결과: {len(existing)}개")

# eval300 로드
data = json.load(open(EVAL_FILE, encoding="utf-8"))
corpus = {e["id"]: e for e in data["corpus"]}
eval_ids = data["ids"]

# 기존 결과 재활용
groundtruth = {eid: existing[eid] for eid in eval_ids if eid in existing}
need_ner = [eid for eid in eval_ids if eid not in existing]
print(f"재활용: {len(groundtruth)}개 | 신규 NER 필요: {len(need_ner)}개")

if need_ner:
    print("SillokBERT-NER 로딩...")
    ner = pipeline(
        "token-classification",
        model="ddokbaro/SillokBert-NER",
        aggregation_strategy="simple",
        device=-1,
    )

    hit, miss = 0, 0
    for eid in tqdm(need_ner, desc="NER"):
        entry = corpus[eid]
        try:
            ents = ner(entry["original"][:512])
        except Exception:
            ents = []

        entities = []
        seen = set()
        for ent in ents:
            tag = ent["entity_group"]
            hanja = ent["word"].strip().replace(" ", "")
            if not hanja or (tag, hanja) in seen:
                continue
            seen.add((tag, hanja))
            korean = hanja_map.get(hanja)
            if korean:
                hit += 1
                entities.append([tag, hanja, korean])
            else:
                miss += 1

        groundtruth[eid] = entities

    total = hit + miss
    print(f"말모이 매핑 성공: {hit}/{total} ({hit/max(total,1)*100:.1f}%)")

print(f"엔티티 있는 항목: {sum(1 for v in groundtruth.values() if v)}/{len(groundtruth)}")

with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(groundtruth, f, ensure_ascii=False, indent=2)
print(f"저장: {OUT_FILE}")
