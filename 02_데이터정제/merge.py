import os
import json
import re
from bs4 import BeautifulSoup
from collections import defaultdict

# --- 1. 경로 설정 ---
history_dir = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\SJW_Corpus_History"
cleaned_dir = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\SJW_Corpus_Cleaned"
output_json = r"C:\Users\kevin\OneDrive\Desktop\sillok_crawler\Merged_Corpus_Final.json"

# 제외할 연도 키워드 (파일명에 A14, A15, A24가 들어가면 스킵)
exclude_keywords = ['A14', 'A15', 'A24']

# 정규식 패턴 세팅
pattern_cn = re.compile(r"^[○\s]*上在[^\s,。]*宮[。\s]*")
pattern_kr = re.compile(r"^상이\s+[^\s]*궁에\s+있었다[.\s]*")

def extract_date_sjw(id_str):
    match = re.search(r'SJW-([A-Z0-9]{3})([0-9]{2})[0-9]([0-9]{2})', id_str)
    if match: return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None

def extract_date_itkc(id_str):
    # ITKC ID 포맷 추출 (유연하게 매칭)
    match = re.search(r'([A-Z0-9]{3})_([0-9]{2})[A-Z]_([0-9]{2})[A-Z]', id_str)
    if match: return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None

print("🔥 파일명 무시! '날짜 ID' 기반 글로벌 싹쓸이 병합 시작...\n")

# 글로벌 날짜 방 생성
date_rooms = defaultdict(lambda: {"original": [], "translation": [], "h_ids": []})

# --- [STEP 1] 원문(History) 싹쓸이 ---
print("📥 원문 데이터 긁어모으는 중...")
for h_file in os.listdir(history_dir):
    if any(k in h_file for k in exclude_keywords): continue
    h_path = os.path.join(history_dir, h_file)
    if not os.path.isfile(h_path): continue
    
    with open(h_path, 'r', encoding='utf-8') as f_h:
        soup_h = BeautifulSoup(f_h, 'xml')
        for art in soup_h.find_all('article'):
            id_str = art.get('id', '')
            date_key = extract_date_sjw(id_str)
            text = art.find('original').text.strip() if art.find('original') else ""
            if date_key and text:
                date_rooms[date_key]["original"].append(text)
                date_rooms[date_key]["h_ids"].append(id_str)

# --- [STEP 2] 번역문(Cleaned) 싹쓸이 ---
print("📥 번역문 데이터 긁어모으는 중...")
for c_file in os.listdir(cleaned_dir):
    if any(k in c_file for k in exclude_keywords): continue
    c_path = os.path.join(cleaned_dir, c_file)
    if not os.path.isfile(c_path): continue
    
    with open(c_path, 'r', encoding='utf-8') as f_c:
        soup_c = BeautifulSoup(f_c, 'xml')
        for art in soup_c.find_all('article'):
            id_str = art.get('id', '')
            date_key = extract_date_itkc(id_str)
            text = art.find('translation').text.strip() if art.find('translation') else ""
            if date_key and text:
                date_rooms[date_key]["translation"].append(text)

# --- [STEP 3] 날짜 방에서 병합 수술 진행 ---
print("✂️ 기거주(왕의 위치) 핀셋 수술 및 1:1 매칭 진행 중...")
parallel_corpus = []
perfect_count = 0
fixed_count = 0
merged_count = 0
missing_pair_count = 0

for date_key in sorted(date_rooms.keys()):
    data = date_rooms[date_key]
    orig_list = data["original"]
    trans_list = data["translation"]
    h_ids = data["h_ids"]
    
    # 어느 한 쪽이 아예 비어있으면 (짝이 없으면) 매칭 불가
    if not orig_list or not trans_list:
        missing_pair_count += 1
        continue
        
    # [수술 로직] 원문이 1개 더 많고, 원문 첫 기사가 '궁에 있었다'
    if len(orig_list) == len(trans_list) + 1 and pattern_cn.match(orig_list[0]):
        orig_list[1] = orig_list[0] + " " + orig_list[1]
        orig_list.pop(0)
        h_ids.pop(0)
        fixed_count += 1
        
    # [수술 로직] 번역문이 1개 더 많고, 번역문 첫 기사가 '궁에 있었다'
    elif len(trans_list) == len(orig_list) + 1 and pattern_kr.match(trans_list[0]):
        trans_list[1] = trans_list[0] + " " + trans_list[1]
        trans_list.pop(0)
        fixed_count += 1

    # 최종 저장 판정
    if len(orig_list) == len(trans_list):
        for i in range(len(orig_list)):
            parallel_corpus.append({
                "id": h_ids[i],
                "date": date_key,
                "original": orig_list[i],
                "translation": trans_list[i]
            })
        perfect_count += len(orig_list)
    else:
        # 그래도 개수가 다르면 날짜 단위로 통째로 합침
        merged_orig = " ".join(orig_list)
        merged_trans = " ".join(trans_list)
        parallel_corpus.append({
            "id": h_ids[0] if h_ids else "UNKNOWN",
            "date": date_key,
            "original": merged_orig,
            "translation": merged_trans
        })
        merged_count += 1

# --- [STEP 4] JSON 저장 ---
if parallel_corpus:
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump({"corpus": parallel_corpus}, f, ensure_ascii=False, indent=4)
    print("\n========================================")
    print(f"🎉 드디어 최종 병합 완료!")
    print(f" - 1:1 완벽 매칭된 기사: {perfect_count}개")
    print(f" - 왕의 위치 수술로 살려낸 날짜: {fixed_count}일")
    print(f" - 단락이 너무 달라서 통째로 뭉친 날짜: {merged_count}일")
    print(f" - 원문/번역문 중 하나만 있어서 버려진 날짜: {missing_pair_count}일")
    print(f"💾 저장 경로: {output_json}")
    print("========================================")
else:
    print("\n🚨 [에러] 추출된 데이터가 없습니다. 폴더 경로를 다시 확인해주세요.")
  	