from data_index import build_kb
from data_ContextInjection import link_entity

# 1. 시대별 KB 구축 (person_injo.json, person_jeongjo.json 사용)
build_kb('person_injo.json', 'injo')
build_kb('person_jeongjo.json', 'jeongjo')

print("-" * 40)

# 2. 예시 테스트
# 인조 시대 시나리오
res_injo, msg_injo = link_entity("이귀", 1623, "연평부원군 이귀가 아뢰기를", "injo")
print(f"[인조] 결과: {res_injo} | 메시지: {msg_injo}")

# 정조 시대 시나리오
res_jeongjo, msg_jeongjo = link_entity("채제공", 1790, "좌의정 채제공이 물러나며", "jeongjo")
print(f"[정조] 결과: {res_jeongjo} | 메시지: {msg_jeongjo}")