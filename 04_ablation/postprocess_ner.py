"""
few-shot 번역 결과에 NER 후처리 적용
- ner_groundtruth_300.json 에서 (한자, 정답한글) 가져와서
- hanja 라이브러리로 한자 → 음독 변환
- 번역문에서 성씨+이름 길이 기반으로 잘못된 음독 찾아 정답으로 치환
python postprocess_ner.py
"""
import json, re, sys
from pathlib import Path
import hanja as hanja_lib

sys.stdout.reconfigure(encoding='utf-8')

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
                r[d['id']] = (strip(d['hypothesis']), d.get('reference', ''), d.get('src', None))
        except: pass
    return r

def is_korean_syllables(s):
    return bool(re.match(r'^[가-힣]+$', s))

def find_wrong_reading(hyp, surname, name_len, correct_korean):
    """번역문에서 성씨로 시작하는 이름 길이 매칭 → 정답 아닌 것 찾기"""
    candidates = []
    for i in range(len(hyp)):
        if hyp[i] == surname:
            chunk = hyp[i:i+name_len]
            if (len(chunk) == name_len
                    and chunk != correct_korean
                    and is_korean_syllables(chunk)):
                candidates.append((i, chunk))
    return candidates

def apply_ner_fix(hyp, hanja_form, gt_korean):
    """한 엔티티에 대해 교정 시도. (새 텍스트, 교정됐는지) 반환"""
    if gt_korean in hyp:
        return hyp, False  # 이미 정답 있음

    # hanja 라이브러리 음독 확인
    lib_reading = hanja_lib.translate(hanja_form, 'substitution')

    name_len = len(gt_korean)
    if name_len < 2:
        return hyp, False

    surname = gt_korean[0]
    candidates = find_wrong_reading(hyp, surname, name_len, gt_korean)

    if not candidates:
        return hyp, False

    # 후보가 1개면 안전하게 치환, 여러 개면 lib_reading과 같은 게 있는지 우선
    if len(candidates) == 1:
        pos, wrong = candidates[0]
        new_hyp = hyp[:pos] + gt_korean + hyp[pos+name_len:]
        return new_hyp, True

    # 여러 후보: lib_reading이 후보 중에 없으면 스킵 (안전)
    for pos, wrong in candidates:
        if wrong == lib_reading and wrong != gt_korean:
            new_hyp = hyp[:pos] + gt_korean + hyp[pos+name_len:]
            return new_hyp, True

    return hyp, False


# ── 메인 ────────────────────────────────────────────────────────
few_data = load('results300_fewshot.jsonl')
gt       = json.load(open(BASE / 'ner_groundtruth_300.json', encoding='utf-8'))
data     = json.load(open(BASE / 'eval300_1925.json', encoding='utf-8'))

total_ent = 0; already = 0; fixed = 0; unfixable = 0
out_path = BASE / 'results300_fewshot_nerfix.jsonl'

with open(out_path, 'w', encoding='utf-8') as f:
    for eid in data['ids']:
        if eid not in few_data:
            continue
        hyp, ref, src = few_data[eid]
        entities = gt.get(eid, [])

        for typ, hanja_form, korean in entities:
            total_ent += 1
            if korean in hyp:
                already += 1
                continue
            hyp, did_fix = apply_ner_fix(hyp, hanja_form, korean)
            if did_fix:
                fixed += 1
            else:
                unfixable += 1

        row = {'id': eid, 'reference': ref, 'hypothesis': hyp}
        if src: row['src'] = src
        f.write(json.dumps(row, ensure_ascii=False) + '\n')

print(f"전체 엔티티: {total_ent}")
print(f"  이미 정답:  {already} ({already/total_ent*100:.1f}%)")
print(f"  교정 성공:  {fixed}  ({fixed/total_ent*100:.1f}%)")
print(f"  교정 불가:  {unfixable} ({unfixable/total_ent*100:.1f}%)")
print(f"예상 NER recall: {(already+fixed)/total_ent:.3f}  (이전: {already/total_ent:.3f})")
print(f"저장: {out_path}")
