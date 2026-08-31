# 선행 연구 자산 인벤토리 (2026-08-31 이관 기준)

저장소 재편 시 자산의 소재·상태·이관 여부를 기록한다.

## 커밋된 자산

| 자산 | 위치 | 출처 (로컬) | 비고 |
|---|---|---|---|
| KB 인물 메타데이터 (2,690명) | `kb/id_lookup_injo.json` | `malmoi/kb/` | |
| KB 역색인 (9,403 키) | `kb/inverted_index_injo.json` | `malmoi/kb/` | |
| 엔티티 링킹 정본 로직 | `kb/data_ContextInjection.py` | `malmoi/kb/` | ADR-015 참조 |
| KB 빌드 스크립트 | `research/kb-build/{data_db,data_index,main_run}.py` | `malmoi/kb/` | 재생성용 |
| 골든셋 300문장 (원문+참조역) | `eval/eval300_1925.json` | `malmoi/ex3/` | `data/`의 사본과 내용 동일 확인 후 `data/` 삭제 |
| NER 정답셋 (300문서) | `eval/ner_groundtruth_300.json` | `malmoi/ex3/` | |
| 채점기 (BLEU-char/chrF/NER recall) | `eval/score_300.py` | `malmoi/ex3/` | 경로 수정 필요 시 M1에서 |
| 프롬프트 원문 | `docs/prompts.md` | `research/04_ablation/run_kbinject.py`, `fewshot_config.json` | |
| 연구 코드 6단계 | `research/01_크롤러` ~ `research/06_NER` | 루트에서 git mv | 히스토리 보존 |
| 연구 보고서·설계 문서 | `research/docs/` | 루트 untracked에서 이동 | PDF 포함 |

## 커밋하지 않는 자산 (로컬 `malmoi/`에만 존재, .gitignore 처리)

| 자산 | 크기 | 사유 |
|---|---|---|
| `Merged_Corpus_Final.json` (병렬 코퍼스 62,476쌍) | 70.6MB | 대용량. M0 토큰비율 실측·M2 배치 입력으로 로컬 사용 |
| `SJW_CPT_Corpus.txt` (CPT 학습 코퍼스) | 50.3MB | 서빙에 불필요 |
| `인물_관직_이력.csv` (KB 원천) | 41.9MB | `research/kb-build/`로 재생성 가능 |
| `person_master.json` (전 시대 27,329명) | 13MB | 인조 구간만 서빙 대상 |
| 정조 시대 KB (`*_jeongjo.json`) | ~1.6MB | 확장 시 재이관 |
| `id_lookup.json`, `inverted_index.json` | — | injo 파일과 동일한 중복본 |

## 모델 가중치 소재

| 모델 | 소재 | 서빙 계획 |
|---|---|---|
| SillokBERT-NER (BIO 9태그) | HuggingFace Hub `ddokbaro/SillokBert-NER` | M1에서 다운로드 → ONNX INT8 변환 → `ner-server/` 서빙 |
| SillokBERT (CPT base) | HuggingFace Hub `ddokbaro/SillokBert` | 서빙 불필요 (NER 백본으로 이미 반영됨) |
| CPT 원본 체크포인트 | 저자 Google Drive (`malmoi_project/`) — 저장소에 없음 | 사용 안 함 |

## 이관 중 발견된 불일치 (기록)

1. **엔티티 링킹**: README의 "표층형→글자 교집합→글자 합집합" 캐스케이드는 미구현. 실제 코드(`data_ContextInjection.py`: 역색인 후보→활동시기 필터→관직 매칭)를 정본으로 채택. → ADR-015
2. **번역 모델**: README는 "Gemini 2.5 Flash" 단일 기술이나, ablation 실험 러너는 `gemma-4-26b-a4b-it` 사용. Gemini 2.5 Flash는 NER 검증 단계(`research/06_NER/run_ner.py`)에서 사용됨.
3. **README의 PDF 링크 깨짐**: 파일명 불일치 (밑줄 vs 공백·《》). README 재작성(Step 5) 시 수정.
4. `research/06_NER/run_ner.py`에 Windows 절대경로 하드코딩 잔존 — 연구 보존용이므로 수정하지 않음.
