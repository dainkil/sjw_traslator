import pandas as pd
import numpy as np
import json

# 1. 데이터 로드
df = pd.read_csv('인물_관직_이력.csv', encoding='utf-8')

# 2. 생년/몰년 전처리 및 활동 시기 계산
df['생년'] = df['생년'].astype('Int64')
df['몰년'] = df['몰년'].astype('Int64')

min_active_year = df.groupby('인물아이디')['년'].transform('min')
max_active_year = df.groupby('인물아이디')['년'].transform('max')

df['활동_시작'] = df['생년'].fillna(min_active_year)
df['활동_종료'] = df['몰년'].fillna(max_active_year)

# 3. 데이터 정렬 (관직 순서를 연도순으로 유지하기 위함)
df = df.sort_values(by=['인물아이디', '년'])

# 4. 동적 Aggregation 딕셔너리 생성 (자, 호 컬럼이 원본에 있을 경우 자동 포함)
agg_dict = {
    '한자_명': ('한자_명', 'first'),
    '한글_명': ('한글_명', 'first'),
    '본관_표준': ('본관_표준', 'first'),
    '활동_시작': ('활동_시작', 'first'),
    '활동_종료': ('활동_종료', 'first'),
    # dict.fromkeys를 사용하여 순서를 유지하면서 중복 관직 제거
    '관직_리스트': ('관직명_정규화', lambda x: list(dict.fromkeys(x.dropna()))) 
}

if '자' in df.columns:
    agg_dict['자'] = ('자', 'first')
if '호' in df.columns:
    agg_dict['호'] = ('호', 'first')

# 5. 데이터 압축
master_df = df.groupby('인물아이디').agg(**agg_dict).reset_index()

print(f"총 {len(master_df)}명의 인물 데이터가 압축되었습니다.")

# 6. JSON 덮어쓰기
master_df.to_json('person_master.json', orient='records', force_ascii=False, indent=4)
print("person_master.json 파일 저장 완료! (기존 파일 덮어쓰기 됨)")