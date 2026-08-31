import json
from collections import defaultdict

def build_kb(input_file, period_tag):
    # 1. 분리된 데이터 불러오기 
    with open(input_file, 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    inverted_index = defaultdict(list)
    id_lookup = {}

    # 2. 데이터 순회하며 인덱싱
    for person in master_data:
        p_id = person["인물아이디"]
        hanja_name = person["한자_명"]
        hangul_name = person["한글_명"]
        
        # 이름, 자, 호 모두 인덱스에 추가
        names = [hanja_name, hangul_name, person.get("자"), person.get("호")]
        for name in names:
            if name:
                inverted_index[name].append(p_id)
                if len(name) >= 2: # 성씨 탈락 대비
                    inverted_index[name[1:]].append(p_id)
            
        # 상세 정보 저장
        id_lookup[p_id] = {
            "한글_명": hangul_name,
            "한자_명": hanja_name,
            "본관_표준": person["본관_표준"],
            "활동_시작": person.get("활동_시작"),
            "활동_종료": person.get("활동_종료"),
            "관직_리스트": person.get("관직_리스트", [])
        }

    # 3. 시대별 태그를 붙여 저장 
    with open(f'inverted_index_{period_tag}.json', 'w', encoding='utf-8') as f:
        json.dump(inverted_index, f, ensure_ascii=False, indent=4)
    with open(f'id_lookup_{period_tag}.json', 'w', encoding='utf-8') as f:
        json.dump(id_lookup, f, ensure_ascii=False, indent=4)

    print(f"✅ {period_tag} KB 구축 완료: {input_file} 사용")