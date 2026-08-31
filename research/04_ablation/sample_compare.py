import json, random
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).parent

data   = json.load(open(BASE / 'eval300_1925.json', encoding='utf-8'))
ref_map = {e['id']: e for e in data['corpus']}

def load(path):
    r = {}
    for l in open(BASE / path, encoding='utf-8'):
        try:
            d = json.loads(l)
            if 'hypothesis' in d:
                r[d['id']] = d['hypothesis']
        except: pass
    return r

bl  = load('results300_baseline.jsonl')
few = load('results300_fewshot.jsonl')
v4  = load('results300_v4.jsonl')

common = [eid for eid in data['ids'] if eid in bl and eid in few and eid in v4]

random.seed(7)
samples = random.sample(common, 5)

for eid in samples:
    e = ref_map[eid]
    print('=' * 70)
    print(f"[원문] {e['original']}")
    print(f"[정답] {e['reference']}")
    print(f"[BASE] {bl[eid]}")
    print(f"[FEW]  {few[eid]}")
    print(f"[V4]   {v4[eid]}")
print('=' * 70)
