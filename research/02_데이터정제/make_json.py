import os
import xml.etree.ElementTree as ET
import json

# ==========================================
# 1. 사용자 설정
target_dir = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\Sillok_Corpus_Final - 복사본"
output_json = os.path.join(target_dir, "sillok_ordered.json")

def create_json():
    final_list = []
    seen_translations = set()  # 중복 체크용 집합
    idx = 1
    
    files = sorted([f for f in os.listdir(target_dir) if f.endswith(".xml")])
    
    for filename in files:
        try:
            file_path = os.path.join(target_dir, filename)
            tree = ET.parse(file_path)
            
            for article in tree.findall(".//article"):
                art_id = article.get("id")
                
                for s in article.findall(".//s"):
                    orig_node = s.find("original")
                    trans_node = s.find("translation")
                    
                    if orig_node is None or trans_node is None:
                        continue
                        
                    o = (orig_node.text or "").strip()
                    t = (trans_node.text or "").strip()
                    
                    # -------------------------------------------------------
                    # [필터링 조건]
                    # 1. 번역문 기준 10자 이상 ~ 100자 미만 (단문 코퍼스)
                    # 2. 이미 추가된 번역문이 아닐 것 (중복 제거)
                    # -------------------------------------------------------
                    if 10 <= len(t) < 100 and t not in seen_translations:
                        final_list.append({
                            "index": idx, 
                            "article_id": art_id, 
                            "original": o, 
                            "translation": t
                        })
                        seen_translations.add(t)  # 처리된 문장으로 등록
                        idx += 1
                        
        except Exception as e:
            print(f"❌ {filename} 처리 중 오류 발생: {e}")
            pass

    # JSON 저장
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=4)
        
    print(f"✅ 단문 코퍼스 생성 완료 (중복 제거 포함)!")
    print(f"📂 경로: {output_json}")
    print(f"📊 최종 유니크 문장 수: {len(final_list)}개")

if __name__ == "__main__":
    create_json()