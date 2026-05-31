import os
import re
from bs4 import BeautifulSoup

# 1. 파일 경로 설정 (윈도우 경로 역슬래시 처리를 위해 앞에 r을 붙임)
INPUT_DIR = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\SJW_Corpus_Final"
OUTPUT_DIR = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\SJW_Corpus_Cleaned"

# 2. 정제된 파일을 저장할 출력 폴더가 없으면 자동 생성
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# 3. 한자 제거용 정규식 세팅
pattern_bracketed = re.compile(r'\s*\([^가-힣a-zA-Z0-9]*[一-龥㐀-䶿豈-﫿]+[^가-힣a-zA-Z0-9]*\)')
pattern_inline = re.compile(r'[一-龥㐀-䶿豈-﫿]+')

# 4. 폴더 내 모든 파일 순회하며 정제 작업 수행
for filename in os.listdir(INPUT_DIR):
    file_path = os.path.join(INPUT_DIR, filename)
    
    # 폴더인 경우 건너뛰고 파일만 처리
    if not os.path.isfile(file_path):
        continue
        
    print(f"[{filename}] 정제 작업 시작...")
    
    try:
        # 파일 읽기 (인코딩 에러 방지를 위해 utf-8 사용)
        with open(file_path, 'r', encoding='utf-8') as f:
            xml_data = f.read()
            
        # XML 파싱 (설치하신 lxml 파서 활용)
        soup = BeautifulSoup(xml_data, 'xml') 
        
        # <translation> 태그 내용만 찾아 정제
        for translation in soup.find_all('translation'):
            if translation.string:
                text = translation.get_text()
                
                # 정규식으로 한자 제거
                cleaned_text = pattern_bracketed.sub('', text)
                cleaned_text = pattern_inline.sub('', cleaned_text)
                
                # 중복 공백 제거 및 양옆 공백 정리
                cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
                
                # 정제된 텍스트로 태그 내용 덮어쓰기
                translation.string = cleaned_text
                
        # 정제된 내용을 새 폴더에 저장
        output_path = os.path.join(OUTPUT_DIR, filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
        print(f"  -> 완료! ({output_path})")
        
    except Exception as e:
        print(f"  -> 에러 발생 ({filename}): {e}")

print("\n========================================")
print("모든 파일 정제 완료! SJW_Corpus_Cleaned 폴더를 확인하세요.")
print("========================================")