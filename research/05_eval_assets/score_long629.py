"""
5-way ablation: 100자 이상(629개) eval set
조건: baseline / few-shot / expr-injection / kb-injection / combined
지표: BLEU(char) / chrF++(char) / BLEU(morph) / chrF++(morph) / NER recall
"""
import json, re, sys, os
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from sacrebleu.metrics import BLEU, CHRF
from kiwipiepy import Kiwi

EVAL_FILE = "eval_assets/eval_set_1925.json"
NER_GT    = "ablation5way/ner_groundtruth.json"
OUT_FILE  = "ablation5way/ablation_5way_final.txt"
MIN_LEN   = 100

CONDITIONS = [
    ("baseline",        "ablation5way/results_baseline.jsonl"),
    ("few-shot",        "ablation5way/results_fewshot.jsonl"),
    ("expr-inject-v1",  "ablation5way/results_expr_inject.jsonl"),
    ("expr-inject-v3",  "ablation5way/results_expr_inject_v3.jsonl"),
    ("kb-inject",       "ablation5way/results_kb_inject.jsonl"),
    ("combined",        "ablation5way/results_combined.jsonl"),
]

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text).strip()
    # 한자 괄호 제거: (漢字) 형태
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)
    return re.sub(r'\s+', ' ', text).strip()

corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}
long_ids = {eid for eid, e in corpus.items() if len(e["original"]) >= MIN_LEN}
print(f"100자 이상: {len(long_ids)}개")

# NER 답지 로딩
ner_gt = {}
if Path(NER_GT).exists():
    ner_gt = json.load(open(NER_GT, encoding="utf-8"))
    print(f"NER 답지 로딩: {len(ner_gt)}개")
else:
    print("NER 답지 없음 (build_ner_groundtruth.py 먼저 실행)")

# 각 조건 결과 로딩
results = {}
for name, fpath in CONDITIONS:
    if not Path(fpath).exists():
        print(f"  {name}: 파일 없음 → 스킵")
        continue
    hyps = {}
    with open(fpath, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("id") in long_ids and "hypothesis" in r:
                hyps[r["id"]] = strip(r["hypothesis"])
    if not hyps:
        print(f"  {name}: 0개 → 스킵")
        continue
    print(f"  {name}: {len(hyps)}개")
    results[name] = hyps

# 모든 조건에 공통인 ID
common = [eid for eid in long_ids
          if all(eid in results[n] for n in results)]
print(f"\n공통 ID: {len(common)}개\n")

if not common:
    print("공통 ID 없음. 결과 파일을 확인하세요.")
    sys.exit(0)

# 형태소 토크나이저
kiwi = Kiwi()
def morph(text):
    return " ".join(t.form for t in kiwi.tokenize(text))

bleu_char = BLEU(tokenize="char", effective_order=True)
chrf      = CHRF()

def score4(hyps, refs):
    mh = [morph(h) for h in hyps]
    mr = [morph(r) for r in refs]
    bc  = bleu_char.corpus_score(hyps, [refs]).score
    cc  = chrf.corpus_score(hyps, [refs]).score
    bm  = BLEU(tokenize="none", effective_order=True).corpus_score(mh, [mr]).score
    cm  = chrf.corpus_score(mh, [mr]).score
    return bc, cc, bm, cm

def ner_recall(hyps_dict, ids):
    if not ner_gt:
        return None
    hits, total = 0, 0
    for eid in ids:
        hyp = hyps_dict.get(eid, "")
        for tag, hanja, korean in ner_gt.get(eid, []):
            total += 1
            if korean in hyp:
                hits += 1
    return hits / total if total > 0 else 0.0

refs = [corpus[i]["reference"] for i in common]
scores = {}
for name in results:
    hyps = [results[name][i] for i in common]
    bc, cc, bm, cm = score4(hyps, refs)
    nr = ner_recall(results[name], common)
    scores[name] = (bc, cc, bm, cm, nr)

# 출력
W = 14
lines = []
lines.append("=" * (22 + W * 5))
lines.append(f"5-way Ablation  |  100자 이상 공통 eval set (n={len(common)})")
lines.append("=" * (22 + W * 5))
header = f"{'':22}" + "".join(f"{'BLEU(c)':>{W}}{'chrF(c)':>{W}}{'BLEU(m)':>{W}}{'chrF(m)':>{W}}{'NER-rec':>{W}}")
lines.append(f"{'':22}{'BLEU(char)':>{W}}{'chrF++(char)':>{W}}{'BLEU(morph)':>{W}}{'chrF++(morph)':>{W}}{'NER recall':>{W}}")
lines.append("-" * (22 + W * 5))

base_scores = scores.get("baseline")
for name in [c[0] for c in CONDITIONS]:
    if name not in scores:
        lines.append(f"  {name:<20} {'(미완료)':>{W*5}}")
        continue
    bc, cc, bm, cm, nr = scores[name]
    nr_str = f"{nr:.3f}" if nr is not None else "  N/A"
    lines.append(f"  {name:<20}{bc:>{W}.2f}{cc:>{W}.2f}{bm:>{W}.2f}{cm:>{W}.2f}{nr_str:>{W}}")

if base_scores:
    lines.append("-" * (22 + W * 5))
    for name in [c[0] for c in CONDITIONS]:
        if name == "baseline" or name not in scores:
            continue
        bc, cc, bm, cm, nr = scores[name]
        bbc, bcc, bbm, bcm, bnr = base_scores
        nr_diff = f"{nr-bnr:>+.3f}" if (nr is not None and bnr is not None) else "  N/A"
        lines.append(f"  Δ {name:<19}{bc-bbc:>+{W}.2f}{cc-bcc:>+{W}.2f}{bm-bbm:>+{W}.2f}{cm-bcm:>+{W}.2f}{nr_diff:>{W}}")

lines.append("=" * (22 + W * 5))

for l in lines:
    print(l)

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"\n저장: {OUT_FILE}")
