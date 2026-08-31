"""
kb good 결과를 results300_few_nerinject.jsonl에 병합
→ 이후 run_few_nerinject.py 실행 시 나머지 ~70개만 자동으로 채움
"""
import json, re
from pathlib import Path

BASE = Path(__file__).parent

data   = json.load(open(BASE / "eval300_1925.json",         encoding="utf-8"))
corpus = {e["id"]: e for e in data["corpus"]}

kb = {}
with open(BASE / "results300_fixed_kbinject.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            kb[r["id"]] = r
        except:
            pass

my = {}
with open(BASE / "results300_few_nerinject.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if "hypothesis" in r:
                my[r["id"]] = r
        except:
            pass


def is_bad(eid, results):
    if eid not in results:
        return True
    hyp   = results[eid].get("hypothesis", "")
    entry = corpus.get(eid, {})
    ref   = entry.get("reference", "")
    hangul    = len(re.findall(r"[가-힣]", hyp))
    hanja     = len(re.findall(r"[一-鿿]", hyp))
    ratio     = len(hyp) / max(len(ref), 1)
    orig_ratio = len(hyp) / max(len(entry.get("original", "1")), 1)
    return (
        "__TRANSLATION_FAILED__" in hyp
        or (hanja > hangul * 0.3 and hanja > 3)
        or ratio < 0.3
        or orig_ratio < 0.3
    )


# 내꺼(nerinject) 111개 + kb good 중 내꺼에 없는 것 추가
merged = dict(my)  # 내꺼 우선
added = 0
for eid in data["ids"]:
    if eid in merged:
        continue
    if not is_bad(eid, kb):
        merged[eid] = kb[eid]
        added += 1

print(f"기존 nerinject 성공: {len(my)}개")
print(f"kb good 추가:        {added}개")
print(f"병합 후 총:          {len(merged)}개  (나머지 {300 - len(merged)}개는 run_few_nerinject.py가 채움)")

# 덮어쓰기
out_path = BASE / "results300_few_nerinject.jsonl"
with open(out_path, "w", encoding="utf-8") as f:
    for r in merged.values():
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"저장 완료: {out_path}")
