import os
import xml.etree.ElementTree as ET
import re

# ==========================================
# 1. 사용자 설정 (경로 고정)
# ==========================================
target_dir = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\Sillok_Corpus_Final - 복사본"

def load_direct_ids():
    """
    matching.py가 생성한 list_direct.txt에서 쪼개기 성공 ID 목록을 로드
    """
    path = os.path.join(target_dir, "list_direct.txt")
    if not os.path.exists(path):
        print(f"❌ {path} 파일을 찾을 수 없습니다. matching.py를 먼저 실행하세요.")
        return set()
    with open(path, "r", encoding="utf-8") as f:
        # "ID: ksa_... | Count: 5" 형태에서 ID만 추출
        return {line.split("|")[0].replace("ID:", "").strip() for line in f if "ID:" in line}

# ==========================================
# 2. V82 초보수적 엔진 (matching.py와 로직 동기화)
# ==========================================
# 문장 종결 및 화자 패턴
ZH_END = re.compile(r'(?:曰|云|敎|傳|啓|答|議|書|從之|야|矣|乎|焉)[。？?!：:\s]*$')
KO_END = re.compile(r'(?:하였다|아뢰었다|답하였다|전교하였다|이르기를|아뢰기를|가로되|청하였다|내렸다|말하였다|했다|쓰기를|따랐다|하노라|하소서|인정하였다|삼았다|나타났다|내렸다)[.?,!\s]*$')

def split_and_clean(text, is_original=False):
    if not text: return []
    # 한문은 。？?! 기준, 국문은 .?! 기준 분할
    parts = re.split(r'([。？?!])' if is_original else r'([.?!])', text)
    res, curr = [], ""
    for i in range(0, len(parts)-1, 2):
        sentence = (parts[i] + parts[i+1]).strip()
        if not sentence: continue
        if not curr:
            curr = sentence
        else:
            # V82: 화자 선언부나 따옴표 시작은 무조건 병합하여 오프셋 방어
            is_spk = ZH_END.search(curr) if is_original else KO_END.search(curr)
            if is_spk or sentence.startswith(('"', "'", "“", "‘")):
                curr += " " + sentence
            else:
                res.append(curr)
                curr = sentence
    if curr:
        res.append(curr)
    return [p.strip() for p in res if p.strip()]

def update_xml_article(article, o_parts, t_parts):
    """
    XML 내의 기존 텍스트 노드를 제거하고 정형화된 <sentences> 구조로 변경
    """
    # 기존 노드 제거
    for tag in ["original", "translation", "sentences"]:
        node = article.find(tag)
        if node is not None:
            article.remove(node)
    
    # <sentences> 노드 신설
    sentences_node = ET.SubElement(article, "sentences")
    for idx, (o, t) in enumerate(zip(o_parts, t_parts), 1):
        s_node = ET.SubElement(sentences_node, "s", id=str(idx))
        ET.SubElement(s_node, "original").text = o
        ET.SubElement(s_node, "translation").text = t

def process_files():
    direct_ids = load_direct_ids()
    if not direct_ids:
        return

    # XML 파일 목록 (이름순 정렬)
    files = sorted([f for f in os.listdir(target_dir) if f.endswith(".xml")])
    
    print(f"🚀 V82 XML 안전 변환 시작: {target_dir}")

    for filename in files:
        file_path = os.path.join(target_dir, filename)
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            modified = False

            for article in root.findall(".//article"):
                art_id = article.get("id")
                # 기존 텍스트 추출 (sentences 노드가 아직 없을 때를 대비)
                ot_node = article.find("original")
                tt_node = article.find("translation")
                
                # 이미 변환된 파일이면 sentences 내부를 뒤짐
                if ot_node is None or tt_node is None:
                    continue
                
                ot = (ot_node.text or "").strip()
                tt = (tt_node.text or "").strip()
                
                if art_id in direct_ids:
                    # ✅ 검증된 기사: V82 엔진으로 정밀 분할하여 1:1 매핑
                    o_p = split_and_clean(ot, True)
                    t_p = split_and_clean(tt, False)
                    # 최종 안전장치: 다시 한 번 개수 확인
                    if len(o_p) == len(t_p):
                        update_xml_article(article, o_p, t_p)
                    else:
                        # 엇갈림 위험 시 통블록 처리
                        update_xml_article(article, [ot], [tt])
                else:
                    # 💡 불확실한 기사: 기사 전체를 하나의 덩어리(통블록)로 보존
                    update_xml_article(article, [ot], [tt])
                
                modified = True

            if modified:
                # 가독성을 위해 들여쓰기 적용
                ET.indent(tree, space="  ")
                tree.write(file_path, encoding="utf-8", xml_declaration=True)
                print(f"✅ 처리 완료: {filename}")

        except Exception as e:
            print(f"❌ {filename} 처리 중 오류 발생: {e}")

    print("-" * 50)
    print("✨ 모든 XML 파일에 대한 V82 안전 변환이 완료되었습니다.")

if __name__ == "__main__":
    process_files()