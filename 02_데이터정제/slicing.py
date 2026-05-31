import os
import xml.etree.ElementTree as ET
from collections import Counter

# ==========================================
# 1. 사용자 설정
# ==========================================
target_dir = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\Sillok_Corpus_Final - 복사본"

# 단문 기준 (번역문 한글 글자 수 기준)
MIN_LEN = 5
MAX_LEN = 50

def analyze_xml_duplicates():
    # (원문, 번역문) 쌍을 담을 리스트
    sentence_pairs = []
    total_s_tags = 0
    
    # 디렉토리 내 XML 파일 스캔
    files = [f for f in os.listdir(target_dir) if f.endswith(".xml") and "filtering" not in f]
    print(f"📦 {len(files)}개의 XML 파일을 읽어오는 중...")

    for filename in files:
        file_path = os.path.join(target_dir, filename)
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            # 모든 <s> 태그 순회
            for s in root.findall(".//s"):
                total_s_tags += 1
                
                # 원문과 번역문 추출
                orig_node = s.find("original")
                trans_node = s.find("translation")
                
                if orig_node is not None and trans_node is not None:
                    orig_text = (orig_node.text or "").strip()
                    trans_text = (trans_node.text or "").strip()

                    # 한글 번역문 길이 기준으로 필터링 (너무 짧거나 긴 것 제외)
                    if MIN_LEN <= len(trans_text) <= MAX_LEN:
                        # 통문장 일치를 확인하기 위해 튜플로 묶어서 저장
                        sentence_pairs.append((orig_text, trans_text))
                        
        except Exception as e:
            print(f"❌ {filename} 처리 중 오류 발생: {e}")

    # ==========================================
    # 2. 통계 산출
    # ==========================================
    counts = Counter(sentence_pairs)
    
    # 2회 이상 완벽히 똑같이 등장하는 문장들
    duplicates = {pair: count for pair, count in counts.items() if count > 1}
    
    # 정렬 (가장 많이 반복되는 순서)
    sorted_duplicates = sorted(duplicates.items(), key=lambda x: x[1], reverse=True)

    print("\n" + "="*60)
    print(f"📊 [데이터 분석 요약]")
    print(f"· 전체 탐색된 문장(<s>) 개수: {total_s_tags:,}개")
    print(f"· 길이 기준({MIN_LEN}~{MAX_LEN}자) 통과 단문: {len(sentence_pairs):,}개")
    print(f"· 중복 없는 순수 유니크 문장: {len(counts):,}개")
    print(f"· 중복 발생한 문장 종류: {len(duplicates):,}종")
    print("="*60)

    # 결과 출력
    if sorted_duplicates:
        print(f"\n🔥 [가장 많이 반복되는 통문장 Top 20]")
        print(f"{'회수':<6} | {'번역문 (원문)'}")
        print("-" * 60)
        for pair, count in sorted_duplicates[:20]:
            # 너무 길면 잘라서 출력
            display_trans = (pair[1][:40] + '..') if len(pair[1]) > 40 else pair[1]
            print(f"{count:<6} | {display_trans} ({pair[0]})")
    else:
        print("\n✅ 중복된 통문장이 없습니다.")

if __name__ == "__main__":
    analyze_xml_duplicates()