import json
import re
from collections import defaultdict

# ==========================================
# 1. 0% 오류율을 위한 앵커 매칭 엔진 (V80)
# ==========================================
ZH_SPEAKER = re.compile(r'(?:曰|云|敎|傳|啓|答|議|書|從之)[：:\s]*$')
KO_SPEAKER = re.compile(r'(?:하였다|아뢰었다|답하였다|전교하였다|이르기를|아뢰기를|가로되|청하였다|내렸다|말하였다|했다|쓰기를|따랐다)[.?,!\s]*$')

def is_aligned(o_p, t_p):
    """
    기사 내의 모든 문장이 화자/서술문 성격에서 일치하는지 검증
    """
    if len(o_p) != len(t_p): return False
    for o, t in zip(o_p, t_p):
        o_is_spk = bool(ZH_SPEAKER.search(o[-10:]) or ZH_SPEAKER.search(o[:15]))
        t_is_spk = bool(KO_SPEAKER.search(t[-25:]) or KO_SPEAKER.search(t[:30]))
        if o_is_spk != t_is_spk: return False # 성격이 다르면 즉시 탈락
        if o.startswith(('"', '“')) != t.startswith(('"', '“')): return False
    return True

# ==========================================
# 2. 메인 수술 로직
# ==========================================
def run_repair():
    print("🚀 실록 데이터 전수 검사 및 수술 시작...")
    
    try:
        with open('sillok_ordered.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("❌ 'sillok_ordered.json' 파일을 찾을 수 없습니다.")
        return

    # 기사 단위로 다시 그룹화
    articles = defaultdict(list)
    for item in data:
        articles[item['article_id']].append(item)

    fixed_data = []
    merge_count = 0

    for art_id, group in articles.items():
        # 이미 쪼개진 문장들을 가져옴
        o_list = [s['original'] for s in group]
        t_list = [s['translation'] for s in group]

        # 1문장인 기사는 검사 생략 (무조건 안전)
        if len(o_list) <= 1:
            fixed_data.extend(group)
            continue

        # [V80 정밀 검증] 엇갈림이 발견되면 기사 통째로 합쳐버림
        if is_aligned(o_list, t_list):
            fixed_data.extend(group)
        else:
            # ❌ 위험 감지: 기사 전체를 하나의 문장으로 병합 (안전 장치)
            full_orig = " ".join(o_list)
            full_trans = " ".join(t_list)
            fixed_data.append({
                "article_id": art_id,
                "original": full_orig,
                "translation": full_trans
            })
            merge_count += 1

    # 인덱스 재정렬
    for i, item in enumerate(fixed_data, 1):
        item['index'] = i

    # 최종 저장
    with open('sillok_cleaned_final.json', 'w', encoding='utf-8') as f:
        json.dump(fixed_data, f, ensure_ascii=False, indent=4)

    print("-" * 50)
    print(f"✅ 수술 완료!")
    print(f"🗑️ 내용이 엇갈려 통블록으로 병합된 기사: {merge_count}개")
    print(f"📊 최종 유효 문장 수: {len(fixed_data)}개")
    print(f"💾 저장 완료: sillok_cleaned_final.json")

if __name__ == "__main__":
    run_repair()