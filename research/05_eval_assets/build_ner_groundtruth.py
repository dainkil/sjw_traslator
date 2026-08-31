"""
NER 답지 생성: 원문(한문) 기반 + 말모이 인물 사전
- 원문에 SillokBert-NER → 한자 엔티티 추출
- 말모이 inverted_index_injo로 한자 → 한글명 변환
- 결과를 eval_assets/ner_groundtruth.json 에 저장
  {id: [(tag, hanja, korean), ...], ...}
- 나중에 각 조건별 recall은 별도 스크립트로 계산
"""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
from transformers import pipeline
from tqdm import tqdm

EVAL_FILE     = "eval_assets/eval_set_1925.json"
MALMOI_INDEX  = "말모이/inverted_index_injo.json"
MALMOI_MASTER = "말모이/person_master.json"
OUT_FILE      = "ablation5way/ner_groundtruth.json"
MIN_LEN       = 100

print("말모이 인물 사전 로딩...")
pm_list = json.load(open(MALMOI_MASTER, encoding="utf-8"))
# person_master 전체로 한자_명 → 한글_명 직접 매핑 (26,272개)
hanja_map = {}
for p in pm_list:
    h = (p.get("한자_명") or "").strip().lstrip("﻿")
    k = (p.get("한글_명") or "").strip()
    if h and k:
        hanja_map[h] = k
# inverted_index로 추가 보완 (단일자 약칭 등)
inv = json.load(open(MALMOI_INDEX, encoding="utf-8"))
pm_by_id = {p["인물아이디"]: p for p in pm_list}
for key, ids in inv.items():
    if key not in hanja_map and ids:
        k = pm_by_id.get(ids[0], {}).get("한글_명", "")
        if k:
            hanja_map[key] = k
print(f"한자→한글 매핑: {len(hanja_map)}개")

def hanja_to_korean(hanja):
    return hanja_map.get(hanja)

print("NER 모델 로딩...")
ner = pipeline(
    "token-classification",
    model="ddokbaro/SillokBert-NER",
    aggregation_strategy="simple",
    device=-1,
)

corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]
          if len(e["original"]) >= MIN_LEN}

groundtruth = {}
hit, miss = 0, 0

for eid, entry in tqdm(corpus.items(), desc="NER 답지 생성"):
    try:
        ents = ner(entry["original"][:512])
    except Exception:
        ents = []

    entities = []
    seen = set()
    for ent in ents:
        tag, hanja = ent["entity_group"], ent["word"].strip().replace(" ", "")
        if not hanja or (tag, hanja) in seen:
            continue
        seen.add((tag, hanja))
        korean = hanja_to_korean(hanja)
        if korean:
            hit += 1
            entities.append([tag, hanja, korean])
        else:
            miss += 1

    groundtruth[eid] = entities

total = hit + miss
print(f"\n말모이 매핑 성공: {hit}/{total} ({hit/max(total,1)*100:.1f}%)")
print(f"엔티티 있는 항목: {sum(1 for v in groundtruth.values() if v)}개/{len(groundtruth)}개")

with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(groundtruth, f, ensure_ascii=False, indent=2)
print(f"저장: {OUT_FILE}")
