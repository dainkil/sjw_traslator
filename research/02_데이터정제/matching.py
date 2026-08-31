import os
import xml.etree.ElementTree as ET
import re

# ==========================================
# 1. 경로 설정 (사용자님 경로 고정)
# ==========================================
target_dir = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\Sillok_Corpus_Final - 복사본"
output_direct = os.path.join(target_dir, "list_direct.txt") 
output_seal   = os.path.join(target_dir, "list_seal.txt")   

# [V82 핵심] 문장 종결 및 화자 패턴
ZH_END = re.compile(r'(?:曰|云|敎|傳|啓|答|議|書|從之|也|矣|乎|焉)[。？?!：:\s]*$')
KO_END = re.compile(r'(?:하였다|아뢰었다|답하였다|전교하였다|이르기를|아뢰기를|가로되|청하였다|내렸다|말하였다|했다|쓰기를|따랐다|하노라|하소서|인정하였다|삼았다|나타났다|내렸다)[.?,!\s]*$')

def split_and_clean(text, is_original=False):
    if not text: return []
    parts = re.split(r'([。？?!])' if is_original else r'([.?!])', text)
    res, curr = [], ""
    for i in range(0, len(parts)-1, 2):
        sentence = (parts[i] + parts[i+1]).strip()
        if not sentence: continue
        if not curr: curr = sentence
        else:
            # V82: 화자 선언부나 따옴표 시작은 무조건 병합하여 오프셋 방어
            is_spk = ZH_END.search(curr) if is_original else KO_END.search(curr)
            if is_spk or sentence.startswith(('"', "'", "“", "‘")):
                curr += " " + sentence
            else:
                res.append(curr); curr = sentence
    if curr: res.append(curr)
    return [p.strip() for p in res if p.strip()]

def is_semantic_match(o_p, t_p):
    """
    V82: 모든 슬라이스 문장의 '성격'이 1:1로 대응하는지 검증
    """
    if len(o_p) != len(t_p): return False
    for o, t in zip(o_p, t_p):
        # 앵커 체크: 둘 다 화자문이거나, 둘 다 일반 서술문이어야 함
        o_spk = bool(ZH_END.search(o[-10:]) or ZH_END.search(o[:15]))
        t_spk = bool(KO_END.search(t[-25:]) or KO_END.search(t[:30]))
        if o_spk != t_spk: return False
        
        # 따옴표 일치성 체크
        if o.startswith(('"', '“')) != t.startswith(('"', '“')): return False
    return True

def run_triage():
    direct, seal = [], []
    files = sorted([f for f in os.listdir(target_dir) if f.endswith(".xml")])
    print(f"🚀 V82 분석 시작: {target_dir}")
    
    for filename in files:
        try:
            tree = ET.parse(os.path.join(target_dir, filename))
            for article in tree.findall(".//article"):
                art_id = article.get("id")
                o_p = split_and_clean(article.find("original").text or "", True)
                t_p = split_and_clean(article.find("translation").text or "", False)
                
                # 15문장 이하의 '완벽하게 대칭되는' 기사만 선별
                if 0 < len(o_p) == len(t_p) <= 15 and is_semantic_match(o_p, t_p):
                    direct.append(f"ID: {art_id} | Count: {len(o_p)}")
                else:
                    seal.append(f"ID: {art_id} | Reason: High Drift Risk")
        except: pass

    with open(output_direct, "w", encoding="utf-8") as f: f.write("\n".join(direct))
    with open(output_seal, "w", encoding="utf-8") as f: f.write("\n".join(seal))
    print(f"✅ 완료 (Direct: {len(direct)} / Seal: {len(seal)})")

if __name__ == "__main__":
    run_triage()