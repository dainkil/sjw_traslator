import json, re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
from sacrebleu.metrics import BLEU, CHRF
from kiwipiepy import Kiwi

BASE = Path(__file__).parent

def strip(text):
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    text = re.sub(r'^○\s*', '', text.strip())
    text = re.sub(r'\s*○\s*', ' ', text).strip()
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def load_results(path):
    results = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if 'hypothesis' in r:
                        results[r['id']] = strip(r['hypothesis'])
                except: pass
    except FileNotFoundError: pass
    return results

CONDITIONS = {
    'baseline': BASE / 'results300_baseline.jsonl',
    'few-shot': BASE / 'results300_fewshot.jsonl',
    'v4':       BASE / 'results300_v4.jsonl',
    'hybrid':   BASE / 'results300_hybrid.jsonl',
}

loaded     = {c: load_results(p) for c, p in CONDITIONS.items()}
data       = json.load(open(BASE / 'eval300_1925.json', encoding='utf-8'))
ref_map    = {e['id']: e['reference'] for e in data['corpus']}
groundtruth = json.load(open(BASE / 'ner_groundtruth_300.json', encoding='utf-8'))

common_ids = [eid for eid in data['ids'] if all(eid in loaded[c] for c in CONDITIONS) and eid in ref_map]
refs = [ref_map[eid] for eid in common_ids]
print(f'공통 n={len(common_ids)}')

print('형태소 분석 중...')
kiwi   = Kiwi()
refs_m = [' '.join(t.form for t in kiwi.tokenize(r)) for r in refs]

W = 95
results_table = {}
for cond in CONDITIONS:
    hyps   = [loaded[cond][eid] for eid in common_ids]
    bc     = BLEU(tokenize='char', effective_order=True).corpus_score(hyps, [refs]).score
    cc     = CHRF().corpus_score(hyps, [refs]).score
    hyps_m = [' '.join(t.form for t in kiwi.tokenize(h)) for h in hyps]
    bm     = BLEU(tokenize='none', effective_order=True).corpus_score(hyps_m, [refs_m]).score
    cm     = CHRF().corpus_score(hyps_m, [refs_m]).score
    ids_ent = [eid for eid in common_ids if groundtruth.get(eid)]
    hits    = sum(1 for eid in ids_ent for _,_,korean in groundtruth[eid] if korean in loaded[cond][eid])
    total   = sum(len(groundtruth[eid]) for eid in ids_ent)
    ner     = hits / max(total, 1)
    results_table[cond] = (bc, cc, bm, cm, ner)
    print(f'  {cond} 완료')

b0 = results_table['baseline']
lines = [
    '=' * W,
    f'[목업] 3-way Ablation | n={len(common_ids)}',
    '=' * W,
    f"{'':18s}  {'BLEU(c)':>9}  {'chrF(c)':>9}  {'BLEU(m)':>9}  {'chrF(m)':>9}  {'NER-ALL':>9}",
    '-' * W,
]
for cond, (bc, cc, bm, cm, ner) in results_table.items():
    lines.append(f'  {cond:16s}  {bc:>9.2f}  {cc:>9.2f}  {bm:>9.2f}  {cm:>9.2f}  {ner:>9.3f}')
lines.append('-' * W)
for cond in ['few-shot', 'v4']:
    bc, cc, bm, cm, ner = results_table[cond]
    lines.append(f'  D {cond:14s}  {bc-b0[0]:>+9.2f}  {cc-b0[1]:>+9.2f}  {bm-b0[2]:>+9.2f}  {cm-b0[3]:>+9.2f}  {ner-b0[4]:>+9.3f}')
lines.append('=' * W)

print('\n' + '\n'.join(lines))
