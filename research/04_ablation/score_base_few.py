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

def load(path):
    r = {}
    for l in open(BASE / path, encoding='utf-8'):
        try:
            d = json.loads(l)
            if 'hypothesis' in d:
                r[d['id']] = strip(d['hypothesis'])
        except: pass
    return r

data    = json.load(open(BASE / 'eval300_1925.json', encoding='utf-8'))
ref_map = {e['id']: e['reference'] for e in data['corpus']}
gt      = json.load(open(BASE / 'ner_groundtruth_300.json', encoding='utf-8'))

bl  = load('results300_baseline.jsonl')
few = load('results300_fewshot.jsonl')

common = [eid for eid in data['ids'] if eid in bl and eid in few and eid in ref_map]
refs   = [ref_map[eid] for eid in common]
print(f'공통 n={len(common)}')

print('형태소 분석 중...')
kiwi   = Kiwi()
refs_m = [' '.join(t.form for t in kiwi.tokenize(r)) for r in refs]

W = 80
results = {}
for name, loaded in [('baseline', bl), ('few-shot', few)]:
    hyps   = [loaded[eid] for eid in common]
    bc     = BLEU(tokenize='char', effective_order=True).corpus_score(hyps, [refs]).score
    cc     = CHRF().corpus_score(hyps, [refs]).score
    hyps_m = [' '.join(t.form for t in kiwi.tokenize(h)) for h in hyps]
    bm     = BLEU(tokenize='none', effective_order=True).corpus_score(hyps_m, [refs_m]).score
    cm     = CHRF().corpus_score(hyps_m, [refs_m]).score
    ids_ent = [eid for eid in common if gt.get(eid)]
    hits    = sum(1 for eid in ids_ent for _,_,k in gt[eid] if k in loaded[eid])
    total   = sum(len(gt[eid]) for eid in ids_ent)
    ner     = hits / max(total, 1)
    results[name] = (bc, cc, bm, cm, ner)

b0 = results['baseline']
lines = [
    '=' * W,
    f'baseline vs few-shot | n={len(common)} (300개 완전 비교)',
    '=' * W,
    f"{'':18s}  {'BLEU(c)':>9}  {'chrF(c)':>9}  {'BLEU(m)':>9}  {'chrF(m)':>9}  {'NER':>7}",
    '-' * W,
]
for name, (bc, cc, bm, cm, ner) in results.items():
    lines.append(f'  {name:16s}  {bc:>9.2f}  {cc:>9.2f}  {bm:>9.2f}  {cm:>9.2f}  {ner:>7.3f}')
lines.append('-' * W)
bc, cc, bm, cm, ner = results['few-shot']
lines.append(f'  {"Δ few-shot":16s}  {bc-b0[0]:>+9.2f}  {cc-b0[1]:>+9.2f}  {bm-b0[2]:>+9.2f}  {cm-b0[3]:>+9.2f}  {ner-b0[4]:>+7.3f}')
lines.append('=' * W)
print('\n' + '\n'.join(lines))
