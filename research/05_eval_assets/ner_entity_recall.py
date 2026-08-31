"""
NER entity recall: 원문(한문) 기반 + 말모이 인물 사전
1. 원문에 SillokBert-NER 적용 → 한자 개체명 추출
2. 말모이 inverted_index로 한자 → 한글명 변환
3. baseline/few-shot hypothesis에서 한글명 존재 여부 확인
4. 태그별(PER/LOC/POH/DAT) 세부 recall 출력
"""
import json, re, sys
sys.stdout.reconfigure(encoding='utf-8')
from transformers import pipeline
from tqdm import tqdm
from collections import defaultdict

EVAL_FILE     = "eval_assets/eval_set_1925.json"
BASELINE_FILE = "bleu_results_gemma4_26b.jsonl"
FEWSHOT_FILE  = "eval_assets/results_fewshot_gemma.jsonl"
MALMOI_INDEX  = "말모이/inverted_index_injo.json"
MALMOI_MASTER = "말모이/person_master.json"
OUT_FILE      = "eval_assets/ner_entity_recall.txt"
MIN_LEN       = 100

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

# 말모이 로딩
print("말모이 인물 사전 로딩...")
pm_list = json.load(open(MALMOI_MASTER, encoding="utf-8"))
person_master = {p["인물아이디"]: p for p in pm_list}
inverted_index = json.load(open(MALMOI_INDEX, encoding="utf-8"))

def hanja_to_korean(hanja_word):
    """한자 → 말모이 inverted_index → 한글명 반환. 없으면 None."""
    ids = inverted_index.get(hanja_word)
    if not ids:
        return None
    p = person_master.get(ids[0], {})
    return p.get("한글_명")

print("NER 모델 로딩...")
ner = pipeline(
    "token-classification",
    model="ddokbaro/SillokBert-NER",
    aggregation_strategy="simple",
    device=-1,
)

corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]
          if len(e["original"]) >= MIN_LEN}

baseline = {}
with open(BASELINE_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("id") in corpus and "hypothesis" in r:
            baseline[r["id"]] = strip(r["hypothesis"])

fewshot = {}
with open(FEWSHOT_FILE, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("id") in corpus and "hypothesis" in r:
            fewshot[r["id"]] = strip(r["hypothesis"])

ids = [eid for eid in corpus if eid in baseline]
print(f"분석 대상: {len(ids)}개 (fewshot 있는 것: {sum(1 for i in ids if i in fewshot)}개)\n")

tag_stats = defaultdict(lambda: {"ref_total": 0, "base_hit": 0, "few_hit": 0})
results = []
malmoi_hit_count = 0
malmoi_miss_count = 0

for eid in tqdm(ids, desc="NER 분석 (원문+말모이)"):
    orig  = corpus[eid]["original"]
    hyp_b = baseline[eid]
    hyp_f = fewshot.get(eid, "")

    # 1. 원문(한문)에 NER
    try:
        orig_ents = ner(orig[:512])
    except Exception:
        orig_ents = []

    # 2. 한자 → 말모이로 한글명 변환
    entities = []  # (tag, hanja, korean)
    seen = set()
    for ent in orig_ents:
        tag, hanja = ent["entity_group"], ent["word"].strip()
        if not hanja or (tag, hanja) in seen:
            continue
        seen.add((tag, hanja))
        korean = hanja_to_korean(hanja)
        if korean:
            malmoi_hit_count += 1
            entities.append((tag, hanja, korean))
        else:
            malmoi_miss_count += 1

    ref_korean = {korean for _, _, korean in entities}

    base_hit = {k for k in ref_korean if k in hyp_b}
    few_hit  = {k for k in ref_korean if k in hyp_f} if hyp_f else set()

    for tag, hanja, korean in entities:
        tag_stats[tag]["ref_total"] += 1
        if korean in hyp_b:
            tag_stats[tag]["base_hit"] += 1
        if hyp_f and korean in hyp_f:
            tag_stats[tag]["few_hit"] += 1

    results.append({
        "id": eid,
        "ref_n": len(ref_korean),
        "base_recall": len(base_hit) / max(len(ref_korean), 1),
        "few_recall":  len(few_hit)  / max(len(ref_korean), 1) if hyp_f else None,
    })

total_ents = malmoi_hit_count + malmoi_miss_count
print(f"\n말모이 매핑 성공: {malmoi_hit_count}/{total_ents} ({malmoi_hit_count/max(total_ents,1)*100:.1f}%)")

has_ent  = [r for r in results if r["ref_n"] > 0]
has_both = [r for r in has_ent if r["few_recall"] is not None]
avg_base = sum(r["base_recall"] for r in has_ent) / max(len(has_ent), 1)
avg_few  = sum(r["few_recall"]  for r in has_both) / max(len(has_both), 1)

lines = []
lines.append("=" * 60)
lines.append("Gemma 고유명사 보존율 (NER + 말모이 인물 사전, 원문 기반)")
lines.append(f"분석: {len(ids)}개 (말모이 매핑 성공 엔티티 있는 항목: {len(has_ent)}개)")
lines.append(f"말모이 매핑: {malmoi_hit_count}/{total_ents} ({malmoi_hit_count/max(total_ents,1)*100:.1f}%)")
lines.append("=" * 60)
lines.append(f"{'':20} {'baseline':>12} {'few-shot':>12}")
lines.append(f"{'평균 recall':20} {avg_base:>12.3f} {avg_few:>12.3f}")
lines.append("")
lines.append("태그별 recall:")
lines.append(f"  {'태그':6} {'ref건수':>8} {'base recall':>12} {'few recall':>12}")
for tag in ["PER", "LOC", "POH", "DAT"]:
    s = tag_stats[tag]
    if s["ref_total"] == 0:
        continue
    br = s["base_hit"] / s["ref_total"]
    fr = s["few_hit"]  / s["ref_total"]
    lines.append(f"  {tag:6} {s['ref_total']:>8} {br:>12.3f} {fr:>12.3f}")

lines.append("")
few_better = sum(1 for r in has_both if r["few_recall"] > r["base_recall"])
few_worse  = sum(1 for r in has_both if r["few_recall"] < r["base_recall"])
lines.append(f"few-shot이 더 잘 보존:  {few_better}개")
lines.append(f"few-shot이 더 못 보존:  {few_worse}개")
lines.append(f"동일:                    {len(has_both) - few_better - few_worse}개")
lines.append("=" * 60)

for l in lines:
    print(l)

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"\n저장: {OUT_FILE}")
