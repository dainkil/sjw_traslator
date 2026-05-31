import os
import xml.etree.ElementTree as ET
import json

# ==========================================
# 1. 사용자 설정
# ==========================================
target_dir = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\Sillok_Corpus_Final"
output_json = os.path.join(target_dir, "sillok_short_clean.json")

def create_short_corpus():
    final_list = []
    seen_translations = set()
    idx = 1
    
    if not os.path.exists(target_dir):
        print(f"❌ 경로를 찾을 수 없습니다: {target_dir}")
        return

    files = sorted([f for f in os.listdir(target_dir) if f.endswith(".xml")])
    print(f"🔎 총 {len(files)}개의 XML 파일을 찾았습니다. 처리를 시작합니다...")
    
    for filename in files:
        try:
            file_path = os.path.join(target_dir, filename)
            tree = ET.parse(file_path)
            
            # 모든 article 태그 확인
            for article in tree.findall(".//article"):
                art_id = article.get("id")
                
                # 1. article 바로 아래에 데이터가 있는지, 아니면 <s> 태그 아래에 있는지 확인
                # 두 구조 모두 대응할 수 있도록 함
                targets = article.findall(".//s")
                if not targets:
                    targets = [article] # <s>가 없으면 article 자체에서 찾음

                for node in targets:
                    o_node = node.find("original")
                    t_node = node.find("translation")
                    
                    if o_node is None or t_node is None:
                        continue
                        
                    o = (o_node.text or "").strip()
                    t = (t_node.text or "").strip()
                    
                    # -------------------------------------------------------
                    # [필터링 조건 완화]
                    # 1. 단문: 번역문 10자 이상 ~ 100자 미만
                    # 2. 중복 제거
                    # 3. 비율: 단문 특성상 국문이 짧을 수 있으므로 0.4 ~ 6.0으로 확장
                    # -------------------------------------------------------
                    if 10 <= len(t) < 100 and t not in seen_translations:
                        if len(o) > 0:
                            ratio = len(t) / len(o)
                            if 0.4 < ratio < 6.0: 
                                final_list.append({
                                    "index": idx, 
                                    "article_id": art_id, 
                                    "original": o, 
                                    "translation": t
                                })
                                seen_translations.add(t)
                                idx += 1
                                
        except Exception as e:
            print(f"⚠️ {filename} 처리 중 오류: {e}")
            continue

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=4)
        
    print("-" * 50)
    print(f"✅ 단문 코퍼스 추출 완료!")
    print(f"📊 최종 유니크 단문 수: {len(final_list)}개")
    print(f"📂 결과 파일: {output_json}")

if __name__ == "__main__":
    create_short_corpus()