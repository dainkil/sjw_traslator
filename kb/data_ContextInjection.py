import json
import re

def link_entity(mention_name, current_year, context_text, period):
    # 해당 시대의 KB 로드
    try:
        with open(f'inverted_index_{period}.json', 'r', encoding='utf-8') as f:
            inverted_index = json.load(f)
        with open(f'id_lookup_{period}.json', 'r', encoding='utf-8') as f:
            id_lookup = json.load(f)
    except FileNotFoundError:
        return None, f" {period} 시대의 KB 파일이 없습니다."

    # [Step 1: 후보군 생성]
    candidates = inverted_index.get(mention_name, [])
    if not candidates:
        return None, " 인덱스에 존재하지 않는 이름입니다."
    
    if len(candidates) == 1:
        return candidates, " 단일 후보"

    # [Step 2: 시간 필터링]
    time_filtered = [c_id for c_id in candidates if id_lookup[c_id].get("활동_시작", 0) <= current_year]

    if len(time_filtered) == 1:
        return time_filtered, " 시간 필터링 완료"

    # [Step 3: 관직명 기반 중의성 해소]
    job_filtered = []
    for c_id in time_filtered:
        jobs = id_lookup[c_id].get("관직_리스트", [])
        for job in jobs:
            clean_job = re.sub(r'\(.*?\)', '', job).strip()
            if clean_job in context_text:
                job_filtered.append(c_id)
                break

    if len(job_filtered) == 1:
        return job_filtered, "✅ 관직명 매칭 완료"
    
    return job_filtered if job_filtered else time_filtered[:3], "⚠️ 복수 후보 반환"