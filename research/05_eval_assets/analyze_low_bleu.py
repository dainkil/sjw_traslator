"""두 모델 모두 낮은 케이스 유형 분석"""
import json, re
from collections import Counter

EVAL_FILE    = "eval_assets/eval_set_1925.json"
SENT_FILE    = "eval_assets/sentence_bleu_results.json"
BASELINE_FILE= "bleu_results_gemma4_26b.jsonl"
FEWSHOT_FILE = "eval_assets/results_fewshot_gemma.jsonl"
OUT_FILE     = "eval_assets/low_bleu_analysis.txt"

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

corpus   = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}
sent_res = {r["id"]: r for r in json.load(open(SENT_FILE, encoding="utf-8"))}

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

# 둘 다 낮은 케이스 (threshold: avg < 25)
low = []
for eid, sr in sent_res.items():
    avg = (sr["baseline"] + sr["fewshot"]) / 2
    if avg < 25 and eid in corpus and eid in baseline and eid in fewshot:
        low.append((avg, eid))

low.sort()
print(f"둘 다 낮은 케이스 (avg BLEU < 25): {len(low)}개\n")

# 유형 분류 함수
def hanja_ratio(text):
    hanja = len(re.findall(r'[一-鿿]', text))
    return hanja / max(len(text), 1)

def classify(orig, ref, hyp_b, hyp_f):
    types = []
    # 1. 원문이 매우 짧음
    if len(orig) <= 10:
        types.append("짧은원문")
    # 2. 정답에 한자 잔존
    if hanja_ratio(ref) > 0.05:
        types.append("정답한자잔존")
    # 3. 정답이 고유명사 위주 (짧고 이름만)
    if len(ref) <= 15 and re.search(r'[가-힣]{2,3}이?\s*(하직|전교|아뢰)', ref):
        types.append("고유명사위주")
    # 4. 번역이 많이 다름 (레퍼런스 vs hyp 길이 차이 큼)
    ratio = len(hyp_b) / max(len(ref), 1)
    if ratio < 0.5 or ratio > 2.0:
        types.append("길이불일치")
    # 5. 번역 누락 (너무 짧거나 거의 같은 원문 반복)
    if len(hyp_b) < 5 or hanja_ratio(hyp_b) > 0.2:
        types.append("번역누락")
    # 6. 고유명사/관직명 차이
    if re.search(r'판서|참판|참의|정랑|좌랑|도승지|승지|주서|사관', ref):
        types.append("관직명포함")
    if not types:
        types.append("기타")
    return types

type_counter = Counter()
records = []
for avg, eid in low:
    e = corpus[eid]
    hyp_b = baseline[eid]
    hyp_f = fewshot[eid]
    types = classify(e["original"], e["reference"], hyp_b, hyp_f)
    for t in types:
        type_counter[t] += 1
    records.append((avg, eid, e, hyp_b, hyp_f, types))

# 출력
print("유형별 빈도:")
for t, cnt in type_counter.most_common():
    print(f"  {t:15s} {cnt}개")
print()

SEP = "=" * 80
with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write(f"둘 다 낮은 케이스 (avg BLEU < 25): {len(low)}개\n\n")
    f.write("유형별 빈도:\n")
    for t, cnt in type_counter.most_common():
        f.write(f"  {t}: {cnt}개\n")
    f.write("\n")

    # 유형별로 예시 5개씩
    seen_types = set()
    written = {}
    for avg, eid, e, hyp_b, hyp_f, types in records:
        for t in types:
            if t not in written:
                written[t] = []
            if len(written[t]) < 5:
                written[t].append((avg, eid, e, hyp_b, hyp_f, types))

    for t, cnt in type_counter.most_common():
        f.write(f"\n{'='*80}\n")
        f.write(f"[유형: {t}] ({cnt}개 중 최대 5개)\n")
        f.write(f"{'='*80}\n")
        for avg, eid, e, hyp_b, hyp_f, types in written.get(t, []):
            f.write(f"\nID: {eid}  avg_BLEU={avg:.1f}  유형={types}\n")
            f.write(f"  [원문]     {e['original']}\n")
            f.write(f"  [정답]     {e['reference']}\n")
            f.write(f"  [baseline] {hyp_b}\n")
            f.write(f"  [few-shot] {hyp_f}\n")

print(f"저장: {OUT_FILE}")
