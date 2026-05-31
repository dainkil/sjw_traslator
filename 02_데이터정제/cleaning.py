import os
import re
import xml.etree.ElementTree as ET
from glob import glob

TARGET_DIR = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\Sillok_Corpus_Final"

def clean_modern_sillok_noise(text, is_translation, is_modern_file):
    """고종/순종 실록 특유의 노이즈 제거 (원본 정보, 시호 등)"""
    if not text: return ""

    # 1. 원본 출처 정보 제거 (예: 원본 5책 1권 15장 A면)
    text = re.sub(r"원본\s*\d+책\s*\d+권\s*\d+장\s*[AB]면", "", text)

    if is_modern_file:
        if is_translation:
            # 2. 고종/순종 황제 시호 나열 헤더 제거
            text = re.sub(r"(고종|순종)\s+[\w\s]{10,}(태황제|황제)\s+실록\s+제\d+권", "", text)
        else:
            # 원문 한자 시호 헤더 제거
            text = re.sub(r"(高宗|純宗)(太)?皇帝實錄卷之[一二三四五六七八九十\d]+", "", text)

    return text.strip()

def clean_ml_corpus_safe(text, is_translation, is_modern_file):
    if not text: return ""
    text = text.strip()

    # 고종/순종 특유 노이즈 선제거
    text = clean_modern_sillok_noise(text, is_translation, is_modern_file)

    # 공통 꼬리표 제거
    text = re.sub(r"【(태백산|정족산|오대산|적상산)사고본】.*", "", text)
    text = re.sub(r"【국편영인본】.*", "", text)
    text = re.sub(r"【분류】.*", "", text)

    if is_translation:
        text = re.sub(r"\[註\s*\d+\].*", "", text)
        text = re.sub(r"ⓒ.*", "", text) 
        text = re.sub(r"^국역\s*", "", text)
        text = re.sub(r"^\d{3}\)?", "", text)
        text = re.sub(r"(?<=[가-힣])\d{3,}", "", text) # 주석 번호 제거
        text = re.sub(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\U00020000-\U0002FFFF]", "", text) # 한자 제거
    else:
        text = re.sub(r"^원문\s*", "", text).strip()
        text = text.replace("○", "") 

    text = re.sub(r"[\(\)\[\]\{\}【】〈〉《》『』〔〕]", "", text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def select_target_files(file_paths):
    """사용자가 입력한 검색어에 맞는 파일들을 필터링합니다."""
    print("\n" + "="*60)
    print(f"🔎 총 {len(file_paths)}개의 파일이 검색 범위에 있습니다.")
    print("="*60)
    
    user_query = input("정제할 파일명(또는 포함될 단어)을 입력하세요 (전체는 'all'): ").strip().lower()
    
    if user_query == 'all':
        return file_paths
    
    # 입력한 글자가 파일명에 포함되어 있는지 확인
    matched = [f for f in file_paths if user_query in os.path.basename(f).lower()]
    
    if not matched:
        print(f"❌ '{user_query}'가 포함된 파일명을 찾을 수 없습니다.")
        return []
    
    print(f"\n✅ {len(matched)}개의 파일이 선택되었습니다:")
    for m in matched[:10]: # 너무 많으면 상위 10개만 출력
        print(f" - {os.path.basename(m)}")
    if len(matched) > 10:
        print(f" ... 외 {len(matched)-10}개 더 있음")
        
    confirm = input("\n이 파일들을 정제할까요? (y/n): ").strip().lower()
    return matched if confirm == 'y' else []

def process_corpus_files():
    if not os.path.exists(TARGET_DIR):
        print(f"❌ 경로 오류: {TARGET_DIR}")
        return

    xml_files = sorted(glob(os.path.join(TARGET_DIR, "*.xml")))
    target_files = select_target_files(xml_files)
    
    if not target_files:
        print("작업을 취소합니다.")
        return

    success_count = 0
    for file_path in target_files:
        try:
            fname = os.path.basename(file_path)
            is_modern_file = 'sillok_z' in fname # 고종/순종 파일 여부 판단
            
            tree = ET.parse(file_path)
            root = tree.getroot()
            modified = False

            for article in root.findall('article'):
                for tag in ['translation', 'original']:
                    elem = article.find(tag)
                    if elem is not None and elem.text:
                        old_text = elem.text
                        cleaned_text = clean_ml_corpus_safe(old_text, (tag == 'translation'), is_modern_file)
                        
                        if cleaned_text != re.sub(r'\s+', ' ', old_text.strip()):
                            elem.text = cleaned_text
                            modified = True

            if modified:
                tree.write(file_path, encoding="utf-8", xml_declaration=True)
                print(f"✨ 정제 완료: {fname}")
                success_count += 1
            else:
                print(f"✔️ 변경 없음: {fname}")

        except Exception as e:
            print(f"❌ 오류 ({fname}): {e}")

    print(f"\n🎉 작업 완료! {success_count}개 파일 업데이트됨.")

if __name__ == "__main__":
    process_corpus_files()