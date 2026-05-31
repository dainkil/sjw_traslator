"""
SJW_Corpus_Final 국역본에서 조선시대 어투 사전 구축
- 서술어 동의어 그룹 (아뢰다/여쭈다/계달하다 등)
- 고빈도 시대 특화 표현 추출
"""
import os, sys, re, json
from collections import Counter, defaultdict
from xml.etree import ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8')

CORPUS_DIR = "SJW_Corpus_Final"
OUT_FILE   = "eval_assets/expression_dict.json"
STAT_FILE  = "eval_assets/expression_dict_stats.txt"

# ─── 1. 번역문 수집 ───────────────────────────────────────────────
print("번역문 수집 중...")
all_texts = []
for fname in sorted(os.listdir(CORPUS_DIR)):
    if not fname.endswith('.xml'):
        continue
    try:
        content = open(os.path.join(CORPUS_DIR, fname), encoding='utf-8').read()
        inner = content.split('<corpus>', 1)[-1].rsplit('</corpus>', 1)[0]
        root = ET.fromstring('<root>' + inner + '</root>')
        for article in root.findall('.//article'):
            t = article.findtext('translation') or ''
            if t.strip():
                all_texts.append(t.strip())
    except Exception:
        pass

print(f"총 번역문: {len(all_texts)}개\n")

# ─── 2. 시대 어투 패턴 정의 ─────────────────────────────────────────
# 각 의미 그룹별 표현 패턴 (정규식)
EXPRESSION_GROUPS = {
    "보고/아룀": [
        r'아뢰[기어었]',  r'여쭈[기었]', r'계달하[였]', r'상주하[였]',
        r'계하[였기]', r'품하[였기]', r'계문하[였]', r'장계하[였]',
        r'복계하[였]', r'치계하[였]',
    ],
    "명령/하교": [
        r'하교하[였시기]', r'전교하[였시기]', r'분부하[였시기]',
        r'명하[였시기]', r'이르[시었기]', r'하시[었기]',
        r'윤허하[였시]', r'허락하[였시]',
    ],
    "임명/제수": [
        r'삼[았]', r'제수하[였]', r'배수하[였]', r'임명하[였]',
        r'차하[였]', r'낙점하[였]',
    ],
    "죽음": [
        r'졸[하였]', r'훙서하[였]', r'사망하[였]', r'죽[었]',
        r'참수하[였]', r'사사하[였]', r'처형하[였]', r'복주하[였]',
        r'처단하[였]', r'주살하[였]',
    ],
    "청원/요청": [
        r'청하[였기]', r'요청하[였]', r'계청하[였]', r'간청하[였]',
        r'청원하[였]',
    ],
    "거부/반대": [
        r'불허하[였]', r'허락지 않[았]', r'윤허하지 않[았]',
        r'거부하[였]', r'반대하[였]',
    ],
    "행차/이동": [
        r'거둥하[였시]', r'납시[었]', r'행행하[였]', r'환궁하[였]',
        r'출궁하[였]', r'어가[가]',
    ],
}

# ─── 3. 실제 등장 표현 빈도 카운팅 ───────────────────────────────────
print("표현 빈도 분석 중...")
full_corpus = "\n".join(all_texts)

group_counts = {}
for group, patterns in EXPRESSION_GROUPS.items():
    counter = Counter()
    for pat in patterns:
        matches = re.findall(pat, full_corpus)
        for m in matches:
            counter[m] += 1
    group_counts[group] = dict(counter.most_common(20))

# ─── 4. 연어(collocation) 추출 - N-gram 기반 ──────────────────────
print("고빈도 시대 표현 추출 중...")

# 특징적 동사구 패턴 (종결어미 앞 2-4글자)
verb_endings = [
    r'[가-힣]{2,5}하였다', r'[가-힣]{2,5}하시었다',
    r'[가-힣]{2,5}하기를', r'[가-힣]{2,5}하여',
]
verb_counter = Counter()
for pat in verb_endings:
    for m in re.finditer(pat, full_corpus):
        verb_counter[m.group()] += 1

top_verbs = [(v, c) for v, c in verb_counter.most_common(200) if c >= 30]

# ─── 5. 시대 특화 동의어 사전 구성 ───────────────────────────────────
# 수작업 + 코퍼스 검증으로 확정
SYNONYM_DICT = {
    "아뢰다": ["여쭈다", "계달하다", "품하다", "상주하다", "계하다", "복계하다", "치계하다", "장계하다"],
    "명하다": ["하교하다", "전교하다", "분부하다", "이르다"],
    "윤허하다": ["허락하다", "재가하다"],
    "졸하다": ["훙서하다", "사망하다", "세상을 떠나다"],
    "참수하다": ["사사하다", "처형하다", "주살하다", "복주하다", "처단하다"],
    "제수하다": ["삼다", "배수하다", "임명하다", "차하다", "낙점하다"],
    "거둥하다": ["납시다", "행행하다", "어가를 움직이다"],
    "환궁하다": ["돌아오다", "돌아오시다"],
    "청하다": ["계청하다", "간청하다", "청원하다", "요청하다"],
    "불허하다": ["허락지 않다", "윤허하지 않다", "거부하다"],
    "말하기를": ["이르기를", "가로되", "하기를"],
    "대답하기를": ["대답하여 이르기를", "답하기를"],
}

# 코퍼스에서 각 표현 빈도 검증
verified = {}
for canonical, synonyms in SYNONYM_DICT.items():
    entry = {"canonical": canonical, "synonyms": [], "canonical_freq": 0, "synonym_freqs": {}}
    entry["canonical_freq"] = len(re.findall(canonical.replace("다", "[다었여기]"), full_corpus))
    for syn in synonyms:
        freq = len(re.findall(syn.replace("다", "[다었여기]"), full_corpus))
        if freq > 0:
            entry["synonyms"].append(syn)
            entry["synonym_freqs"][syn] = freq
    verified[canonical] = entry

# ─── 6. 고빈도 서술어 클러스터 (자동 추출) ────────────────────────────
# "하였다"로 끝나는 표현 중 고빈도 패턴
pattern_하였다 = re.findall(r'[가-힣]{2,6}하였다', full_corpus)
freq_하였다 = Counter(pattern_하였다).most_common(100)

# ─── 7. 저장 ──────────────────────────────────────────────────────
output = {
    "synonym_dict": verified,
    "group_expressions": group_counts,
    "top_verb_phrases": dict(top_verbs[:100]),
    "top_하였다_patterns": dict(freq_하였다[:50]),
}

with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# 통계 출력
lines = []
lines.append("=" * 60)
lines.append("조선시대 어투 사전 (SJW_Corpus_Final 113K 국역본 기반)")
lines.append("=" * 60)
lines.append(f"입력 번역문: {len(all_texts)}개\n")

lines.append("[동의어 그룹]")
for canonical, entry in verified.items():
    lines.append(f"\n  {canonical} (빈도: {entry['canonical_freq']})")
    for syn, freq in entry["synonym_freqs"].items():
        lines.append(f"    = {syn} ({freq})")

lines.append("\n[의미 그룹별 고빈도 표현]")
for group, counts in group_counts.items():
    if not counts:
        continue
    lines.append(f"\n  [{group}]")
    for expr, cnt in sorted(counts.items(), key=lambda x: -x[1])[:8]:
        lines.append(f"    {expr}: {cnt}회")

lines.append("\n[상위 하였다 패턴 (상위 30개)]")
for expr, cnt in freq_하였다[:30]:
    lines.append(f"  {expr}: {cnt}회")

for l in lines:
    print(l)

with open(STAT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\n저장: {OUT_FILE}")
print(f"저장: {STAT_FILE}")
