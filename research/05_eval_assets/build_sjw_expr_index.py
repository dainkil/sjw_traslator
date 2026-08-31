"""
SJW 코퍼스에서 표현별 빈도 집계 + 예문 추출
- article 단위 카운트 (중복 방지)
- match 주변 문맥 창으로 예문 추출
출력: ablation5way/sjw_expr_index.json
"""
import json, re, sys
from pathlib import Path
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8')

SJW_DIR  = Path("SJW_Corpus_Final")
OUT_FILE = Path("ablation5way/sjw_expr_index.json")

# 대표키 → 검색 패턴 목록
EXPR_PATTERNS = {
    "아뢰기를":       [r'아뢰기를'],
    "전교하기를":     [r'전교하기를', r'하교하기를'],
    "윤허하다":       [r'윤허하[였셨]', r'윤허하[지니]'],
    "윤허하지 않다":  [r'윤허하지 않'],
    "훙서하다":       [r'훙서하[였셨]', r'훙거하[였셨]'],
    "졸하다":         [r'졸하[였셨]'],
    "거둥하다":       [r'거둥하[였셨]'],
    "환궁하다":       [r'환궁하[였셨]'],
    "제수하다":       [r'제수하[였셨]', r'에 제수'],
    "장계하기를":     [r'장계하기를', r'장계[를에]'],
    "치계하기를":     [r'치계하기를', r'치계[를에]'],
    "서계하기를":     [r'서계하기를', r'서계[를에]'],
}

def extract_example(text, pattern, window=80):
    """패턴 매칭 주변 window 글자 추출"""
    m = re.search(pattern, text)
    if not m:
        return None
    start = max(0, m.start() - 15)
    end = min(len(text), m.end() + window)
    snippet = text[start:end].strip()
    # 문장 끊기
    snippet = re.split(r'(?<=[다었음])\s*\n', snippet)[0]
    snippet = snippet.replace('\n', ' ').strip()
    if len(snippet) > 100:
        snippet = snippet[:100] + '…'
    return snippet

def get_translations(xml_file):
    """XML에서 translation 목록 반환 (파싱 실패 시 regex fallback)"""
    try:
        raw = xml_file.read_bytes()
        text_utf8 = raw.decode('utf-8', errors='replace')
        root = ET.fromstring(text_utf8)
        return [a.findtext('translation') or "" for a in root.findall('.//article')]
    except ET.ParseError:
        raw_text = xml_file.read_text(encoding='utf-8', errors='replace')
        return re.findall(r'<translation>(.*?)</translation>', raw_text, re.DOTALL)

index = {k: {"count": 0, "examples": []} for k in EXPR_PATTERNS}

total_files = 0
for xml_file in sorted(SJW_DIR.glob("*.xml")):
    total_files += 1
    translations = get_translations(xml_file)
    for trans in translations:
        if not trans.strip():
            continue
        for key, patterns in EXPR_PATTERNS.items():
            matched = False
            for pat in patterns:
                if re.search(pat, trans):
                    if not matched:
                        index[key]["count"] += 1
                        matched = True
                    if len(index[key]["examples"]) < 5:
                        ex = extract_example(trans, pat)
                        if ex and ex not in index[key]["examples"]:
                            index[key]["examples"].append(ex)

print(f"파싱 완료: {total_files}개 파일\n")
print("표현별 빈도 (article 단위):")
for k, v in sorted(index.items(), key=lambda x: -x[1]["count"]):
    ex = v['examples'][0][:70] if v['examples'] else '없음'
    print(f"  {k}: {v['count']}회")
    if v['examples']:
        print(f"    예) {ex}")

OUT_FILE.parent.mkdir(exist_ok=True)
with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(index, f, ensure_ascii=False, indent=2)
print(f"\n저장: {OUT_FILE}")
