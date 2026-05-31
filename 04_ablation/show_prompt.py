import sys, json, re
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from run_few_aiso import extract_features, get_pattern, get_length_bucket, AISOfewshot, build_smart_m, select_perquery

BASE = Path(".")

# 데이터 로드
data = json.load(open("eval300_1925.json", encoding="utf-8"))
corpus_map = {e["id"]: e for e in data["corpus"]}
config = json.load(open("fewshot_config.json", encoding="utf-8"))
template = config["prompt_template"]

# 풀 구성
eval_ids = set(data["ids"])
raw = json.load(open("Merged_Corpus_Final.json", encoding="utf-8"))
pool = [e for e in raw["corpus"]
        if e["id"] not in eval_ids and e.get("translation","").strip() and e.get("original","").strip()]

X_pool = np.array([extract_features(e["original"]) for e in pool])
aiso = AISOfewshot(n_agents=25, n_iter=120, use_smart_m=True, seed=42)
_, visit = aiso.select(X_pool, n_select=8)

TOP = 500
top_idx = np.argsort(visit)[::-1][:TOP]
top_entries  = [pool[i] for i in top_idx]
top_patterns = [get_pattern(X_pool[i]) for i in top_idx]
top_lengths  = [get_length_bucket(pool[i]["original"]) for i in top_idx]

# 샘플 쿼리 하나 선택
sample_id = data["ids"][0]
entry = corpus_map[sample_id]
orig = entry["original"]

q_feat = extract_features(orig)
q_pat  = get_pattern(q_feat)
selected = select_perquery(orig, top_entries, top_patterns, top_lengths, n_select=5)

print("="*60)
print(f"쿼리 패턴: {q_pat} | 길이: {len(orig)}자")
print(f"원문: {orig[:80]}")
print()
print("[선택된 예시 패턴]")
for i, e in enumerate(selected):
    f = extract_features(e["original"])
    p = get_pattern(f)
    print(f"  {i+1}. {p} | {len(e['original'])}자 | {e['translation'][:50]}...")

examples = "\n".join(f"- {e['translation']}" for e in selected)
prompt = template.format(examples=examples, text=orig)
print()
print("="*60)
print("[실제 프롬프트]")
print(prompt[:800])
