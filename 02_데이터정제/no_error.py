import json

# 1. 제거할 96개 기사의 ID 목록 로드 (이미 생성된 파일 활용)
try:
    with open('error_96_articles.json', 'r', encoding='utf-8') as f:
        error_data = json.load(f)
    # 기사 ID만 추출하여 집합(set)으로 변환
    error_ids = set(error_data.keys())
except FileNotFoundError:
    print("❌ error_96_articles.json 파일을 찾을 수 없습니다.")
    error_ids = set()

# 2. 원본 데이터 로드
with open('sillok_ordered.json', 'r', encoding='utf-8') as f:
    master_data = json.load(f)

# 3. 필터링 실행 (에러 ID에 포함되지 않은 기사만 남김)
cleaned_data = []
removed_count = 0

for item in master_data:
    if item['article_id'] not in error_ids:
        cleaned_data.append(item)
    else:
        removed_count += 1

# 4. 인덱스(index) 재정렬
# 데이터가 삭제되었으므로 1번부터 순서대로 다시 번호를 매깁니다.
for i, item in enumerate(cleaned_data, 1):
    item['index'] = i

# 5. 결과 저장 (원본을 덮어씌우거나 새 파일로 저장)
output_filename = 'sillok_ordered_cleaned.json'
with open(output_filename, 'w', encoding='utf-8') as f:
    json.dump(cleaned_data, f, ensure_ascii=False, indent=4)

print(f"✨ 필터링 완료!")
print(f"🗑️ 제거된 문장 수: {removed_count}개 (총 96개 기사 분량)")
print(f"✅ 남은 문장 수: {len(cleaned_data)}개")
print(f"💾 결과가 '{output_filename}'에 저장되었습니다.")