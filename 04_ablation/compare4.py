import json, sys
sys.stdout.reconfigure(encoding='utf-8')
from sacrebleu.metrics import BLEU, CHRF
from kiwipiepy import Kiwi
from pathlib import Path

BASE = Path(__file__).parent

FILES = {
    'baseline':     'results300_baseline.jsonl',
    'few-shot':     'results300_fewshot.jsonl',
    'few+nerfix':   'results300_fewshot_nerfix.jsonl',
    'nerinject':    'results300_few_nerinject.jsonl',
}

data    = json.load(open(BASE / 'eval300_1925.json', encoding='utf-8'))
ref_map = {e['id']: e['reference'] for e in data['corpus']}
gt      = json.load(open(BASE / 'ner_groundtruth_300.json', encoding='utf-8'))

def load(path):
    r = {}
    with open(BASE / path, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                if 'hypothesis' in d:
                    r[d['id']] = d['hypothesis']
            except:
                pass
    return r

loaded  = {c: load(p) for c, p in FILES.items()}
common  = [eid for eid in data['ids'] if all(eid in loaded[c] for c in FILES)]
refs    = [ref_map[eid] for eid in common]
print(f'공통 n={len(common)}/300\n')

kiwi   = Kiwi()
refs_m = [' '.join(t.form for t in kiwi.tokenize(r)) for r in refs]

header = f"  {'':18s}  {'BLEU(c)':>8}  {'chrF':>8}  {'BLEU(m)':>8}  {'NER':>7}"
print(header)
print('-' * 65)

b0 = None
for cond, ld in loaded.items():
    hyps   = [ld[eid] for eid in common]
    bc     = BLEU(tokenize='char', effective_order=True).corpus_score(hyps, [refs]).score
    cc     = CHRF().corpus_score(hyps, [refs]).score
    hyps_m = [' '.join(t.form for t in kiwi.tokenize(h)) for h in hyps]
    bm     = BLEU(tokenize='none', effective_order=True).corpus_score(hyps_m, [refs_m]).score
    ids_ent = [eid for eid in common if gt.get(eid)]
    hits    = sum(1 for eid in ids_ent for _, _, k in gt[eid] if k in ld[eid])
    total   = sum(len(gt[eid]) for eid in ids_ent)
    ner     = hits / max(total, 1)

    if b0 is None:
        b0 = (bc, cc, bm, ner)
        print(f'  {cond:18s}  {bc:>8.2f}  {cc:>8.2f}  {bm:>8.2f}  {ner:>7.3f}')
    else:
        dbc = bc - b0[0]
        dner = ner - b0[3]
        print(f'  {cond:18s}  {bc:>8.2f}  {cc:>8.2f}  {bm:>8.2f}  {ner:>7.3f}  (d_BLEU(c) {dbc:+.2f} / d_NER {dner:+.3f})')
