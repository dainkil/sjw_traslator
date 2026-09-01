# kb/ — 왕대별 인물 지식베이스

선행 연구에서 구축한 결정론적 엔티티 링킹용 KB. 서빙 시스템이 in-memory로 로드한다 (ADR-004).
왕대는 설정으로 고른다: `KB_NAME=injo|jeongjo` (`FileKnowledgeSource`, ADR-018 — 코드 수정 0줄 교체).

## 파일

| 파일 | 내용 | 규모 |
|---|---|---|
| `id_lookup_injo.json` | 인물 ID → 메타데이터 (`한글_명`, `한자_명`, `본관_표준`, `활동_시작`, `활동_종료`, `관직_리스트`) | 2,690명, 1.6MB |
| `inverted_index_injo.json` | 표층형(한자 이름) → 인물 ID 리스트 역색인 | 9,403 키, 443KB |
| `id_lookup_jeongjo.json` | 정조 연간 동일 스키마 | 2,152명, 1.2MB |
| `inverted_index_jeongjo.json` | 정조 연간 역색인 | 8,030 키, 360KB |
| `data_ContextInjection.py` | 엔티티 링킹 정본 로직 (아래 참조) | — |

## 링킹 알고리즘 (정본)

`link_entity(mention_name, current_year, context_text, period)`:

1. **후보군 생성** — 역색인에서 표층형으로 후보 ID 조회. 단일 후보면 즉시 반환.
2. **시간 필터링** — `활동_시작 <= current_year`인 후보만 남김.
3. **관직명 중의성 해소** — 후보의 `관직_리스트` 중 하나가 문맥 텍스트에 등장하면 채택.

모두 실패 시 시간 필터 통과 후보 상위 3명을 복수 후보로 반환 (모호 플래그 → T2 라우팅 신호, PROJECT_PLAN §5.1).

> **주의:** 선행 연구 README에 기술된 "표층형 → 글자 교집합 → 글자 합집합" 캐스케이드는 코드로 구현된 적이 없다.
> 서빙 시스템은 실제 검증된 위 알고리즘을 정본으로 채택했다. 경위와 근거는 `docs/adr/015-entity-linking-canon.md` 참조.

## 재생성 방법

원천 CSV(`인물_관직_이력.csv`, 41.9MB)와 전 시대 마스터(`person_master.json`, 13MB)는 용량 문제로 커밋하지 않는다 (로컬 `malmoi/kb/`에 보관).

```
research/kb-build/data_db.py     # CSV → person_{period}.json (활동_시작/종료 계산)
research/kb-build/data_index.py  # person_{period}.json → inverted_index / id_lookup
research/kb-build/main_run.py    # 실행 드라이버
```

## KB 버전

버전은 설정값이 아니라 **데이터 파일 체크섬에서 파생**된다: `{name}-{SHA-256 앞 8자리}` (예: `injo-…`, `jeongjo-2abe1183`).
파일이 1바이트라도 바뀌면 버전이 갈리므로 캐시 무효화(`kb_version`을 L2 캐시 키에 포함, ADR-009)가 이 값을 신뢰할 수 있다.
