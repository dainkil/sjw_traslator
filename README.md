# 말모이 팀 — 코드 모음집
**승정원일기 LLM 자동 번역 프로젝트**  
Gemma-4-26B · 평가셋 n=300 · **BLEU(c) 40.61 / ETS 0.888 달성**

---

## 전체 파이프라인

```
[01 크롤링] → [02 데이터 정제] → [06 NER 정답지] → [03 번역실험] → [04 Ablation] → [05 평가 자산]
```

---

## 01_크롤러 — 실록·승정원일기 크롤러 (Go)

Python GIL 한계를 넘기 위해 Go로 작성. Goroutine 기반 병렬 수집 + SmartProxy IP 로테이션.

| 파일 | 설명 |
|------|------|
| `main.go` | **조선왕조실록 메인 크롤러.** `sillok.history.go.kr` 에서 연도·월 단위로 Job 큐를 만들어 Goroutine으로 병렬 수집. goquery로 원문·번역문 파싱, XML로 저장. 이어받기(Resume), 5회 재시도, IP 로테이션 포함. |
| `re_main.go` | **오류 기사 재크롤러.** `error_96_articles.json`의 ID 목록을 읽어 `sillok.history.go.kr/id/{id}` 로 재접속, 파싱 성공분만 `repaired_raw_96.json`으로 출력. |
| `sjw.go` | **승정원일기 원문 크롤러 v1.** `sjw.history.go.kr` 에서 일(Day) 단위 Job으로 원문(`<original>`)만 수집. `SJW_Corpus_Final` XML로 저장. |
| `sjw2.go` | **승정원일기 원문+번역문 크롤러 v2.** `SJW_Corpus_History` 에 인조(A)/정조(G) 왕대별 원문·번역문 쌍 수집. sjw.go 개선판. |
| `fetch_sjw_raw.go` | **SJW HTML 원본 수집기 (5차 핵심).** 평가셋 300개 ID로 `sjw.history.go.kr/id/{id}` HTML을 통째로 저장. `<span class="idx_person">` 인명 태그를 보존해 ETS 정답지 구축에 사용. |
| `go.mod` / `go.sum` | Go 의존성 (goquery, PuerkitoBio) |

---

## 02_데이터정제 — XML → 정제 병렬 코퍼스

| 파일 | 설명 |
|------|------|
| `cleaning.py` | **실록 XML 정제.** 서지정보(【태백산사고본】 등), 각주([註 087]), 저작권(ⓒ), 날씨기호(晴·陰·雨), 원문 한자·번역문 한자 괄호 제거. 고종·순종 시호 헤더 별도 처리. |
| `cleaning_sjw.py` | **SJW XML 정제.** BeautifulSoup XML 파서로 `<translation>` 태그 내 한자(괄호 포함)를 정규식으로 제거, `SJW_Corpus_Cleaned`에 저장. |
| `make_json.py` | **XML → JSON 변환.** 실록 XML의 `<s>` 태그를 파싱해 번역문 10~100자 필터 + 중복 제거 후 `sillok_ordered.json` 생성. |
| `merge.py` | **날짜 ID 기반 코퍼스 병합.** 실록(History)과 SJW(Cleaned) XML을 날짜 키로 방을 만들어 병합. `Merged_Corpus_Final.json` 출력. 인조 시기 A14·A15·A24 연도 제외 처리 포함. |
| `matching.py` | **V82 1:1 문장 매칭 엔진.** 한문 종결 패턴(曰·云·啓·從之 등)과 한국어 종결 패턴(하였다·아뢰었다 등)으로 원문-번역문 문장의 화자/서술문 성격 일치 여부 검증. 성공 ID는 `list_direct.txt`, 실패는 `list_seal.txt`로 분류. |
| `real_final.py` | **최종 단문 코퍼스 추출.** `matching.py`가 생성한 `list_direct.txt`를 읽어 V82 엔진으로 재검증 후 쪼개기 성공 기사만 추출. |
| `slicing.py` | **단문 쌍 추출 및 중복 통계.** `<s>` 태그에서 번역문 5~50자 필터로 단문 쌍을 추출하고 (원문, 번역문) 중복 여부를 통계적으로 분석. |
| `clean_json.py` | **JSON 구조 수정 (V80 앵커 매칭).** `sillok_ordered.json`에서 이미 쪼개진 문장의 화자문/서술문 성격 불일치를 탐지해 병합 교정. |
| `no_error.py` | **오류 기사 제거.** `error_96_articles.json`의 ID 집합으로 `sillok_ordered.json`에서 해당 기사를 필터링, 인덱스 재정렬 후 저장. |
| `top_clean.py` | **BLEU 상위 기사 추출.** `bleu_results_gemma4_26b.jsonl`에서 문장단위 BLEU를 계산해 상위 100·500·1000·2000개 평균·최솟값 통계 출력. |
| `final.py` | **실록 단문 코퍼스 최종 추출.** `Sillok_Corpus_Final` XML에서 `<s>` 태그 없는 경우 `<article>` 직접 파싱, 번역문 10~100자 필터 + 중복 제거. |

---

## 03_번역실험 — 다중 LLM 번역 실행 및 BLEU 측정

| 파일 | 설명 |
|------|------|
| `make_eval_set.py` | **평가셋 1925개 구성.** `Merged_Corpus_Final.json` 3000개 샘플에서 Gemma 문장단위 BLEU ≥ 20 필터 + 중복 제거로 `eval_set_1925.json` 생성. |
| `bleu_eval_multi.py` | **소형 모델 비동기 번역 + BLEU.** HuggingFace Router로 Qwen3-4B·Phi4-mini 동시 번역. `<thought>` 태그 제거 후 문장단위 BLEU(char) 계산. 1000회 부트스트랩 신뢰구간 포함. |
| `bleu_eval_large.py` | **대형 모델 번역 + BLEU.** OpenRouter로 Qwen3-235B·DeepSeek-v3 번역. `<think>/<thought>` 태그 모두 제거. BLEU(char)/chrF/BLEU(형태소) 3지표. |
| `bleu_eval_gemma.py` | **Gemma-4-26B 번역 + 평가셋 구성.** Google Generative AI API로 Gemma 번역 후 문장단위 BLEU ≥ 20 기사만 남겨 평가셋 구성. |
| `analyze_bleu.py` | **BLEU 분포 분석.** 전체 결과에서 평균·표준편차·중앙값·백분위수(5/10/25/50/75/90/95) 및 IQR·Z-score 기반 이상치 경계값 출력. |
| `score_gemma4_26b.py` | **Gemma 결과 채점.** `bleu_results_gemma4_26b.jsonl`에서 문장단위 BLEU 계산 후 중복(reference 기준) 제거, 상위 100~2000개 통계 출력. |
| `score_large.py` | **대형 모델(DeepSeek·Qwen3-235B) 채점.** Kiwi 형태소 분석 포함 BLEU(char)/chrF/BLEU(형태소) 3지표 및 사전 계산된 Gemma 결과와 비교표 출력. |
| `make_comparison.py` | **모델 비교 텍스트 생성.** 기존 계산 결과와 현재 Qwen3-235B 결과를 BLEU(char)/chrF/BLEU(형태소)/chrF(형태소) 4지표로 나란히 출력. |
| `monitor.py` | **ablation 실험 진행 모니터링.** 15초마다 few-shot·v4 결과 파일의 완료 건수를 카운트해 출력. |
| `monitor_progress.py` | **대형 모델 번역 ETA 계산.** DeepSeek·Qwen3-235B 결과 파일을 10초마다 읽어 처리 속도·남은 시간(분)을 실시간 출력. |

---

## 04_ablation — 4단계 번역 전략 ablation 실험 (발표 핵심)

Baseline → Few-shot → NERfix → NERinject 4단계 체계적 비교.

| 파일 | 설명 |
|------|------|
| `run_v4.py` | **Baseline (+ 패턴 조건부 표현 주입).** Gemma-4-26B에 원문만 입력. 한문 패턴(傳敎曰·啓曰 등) 감지 시 한국어 대응 표현 힌트를 추가로 주입하는 실험적 baseline. |
| `run_fewshot.py` | **Few-shot 번역.** `fewshot_config.json`의 5개 고정 예시(REP 패턴)를 프롬프트에 삽입. `.env`에서 API 키 로드, 4회 재시도·quota 에러 대응 포함. |
| `run_few_nerinject.py` | **Few-shot + NERinject (최고 성능).** few-shot 프롬프트에 `ner_groundtruth_300.json`의 인명 목록을 `[등장 인물 — 반드시 아래 한글명 그대로 사용]` 블록으로 삽입. 원문 직전에 위치. |
| `run_kbinject.py` | **KB + SillokBERT + RAG 주입 실험.** SillokBERT-NER → person_master → inverted_index → id_lookup → MLM 키워드까지 모두 프롬프트에 주입하는 풀스택 실험. |
| `run_few_aiso.py` | **AISO 동적 예시 선택 실험.** 원문에서 8차원 피처(길이·啓曰·不許·狀啓·上曰 등) 추출 → 패턴 분류(REP/DEN/MEM/ROY/GEN) → Smart M 행렬 기반 AISO로 전체 코퍼스에서 쿼리별 최적 예시 5개 선택. 결과: 고정 예시보다 BLEU −2.2p 열위. |
| `postprocess_ner.py` | **NERfix 후처리.** `ner_groundtruth_300.json`에서 (한자, 정답한글) 로드 → hanja 라이브러리로 음독 변환 → 번역문에서 성씨+이름 길이 기반으로 잘못 읽은 형태 탐색 → 정답 한글명으로 치환. |
| `merge_nerinject.py` | **NERinject 결과 병합.** `results300_fixed_kbinject.jsonl`의 품질 기준(한자 비율·길이 등) 통과 결과를 `results300_few_nerinject.jsonl`에 병합, 미완료분만 재실행 유도. |
| `ner_recall_300.py` | **4-way ETS/NER Recall 채점.** baseline·few-shot·few+nerfix·few+nerinject 4개 조건을 `ner_groundtruth_300.json` 기준으로 한글명 존재 여부 체크, `entity_preservation_300.txt` 출력. |
| `score_300.py` | **4지표 종합 채점.** BLEU(c)/chrF/BLEU(형태소)/ETS를 baseline·few-shot·few+nerfix·hybrid 4개 조건 동시 계산. Kiwi 형태소 분석 포함. |
| `score300.py` | **3-way ablation 채점.** baseline·few-shot·v4·kb-inject를 300개 공통 완료 ID 기준 BLEU(c)/chrF/BLEU(형태소)로 채점, `ablation_300_result.txt` 저장. |
| `score_base_few.py` | **baseline vs few-shot 비교 채점.** 공통 완료 ID 기준 4지표 + ETS 비교표 출력. |
| `quick_score.py` | **4-way 중간 점수 확인.** 실험 진행 중 공통 완료 건수 및 BLEU/chrF/NER을 빠르게 출력. |
| `quick_aiso_score.py` | **AISO 실험 채점.** baseline·few-shot·few+aiso 3개 조건 비교. |
| `mock_score.py` | **hybrid 조건 포함 채점.** baseline·few-shot·few+nerfix·hybrid 4개 조건 채점. |
| `compare4.py` | **4-way 최종 비교 출력.** baseline/few-shot/few+nerfix/nerinject 4개 조건 BLEU(c)/chrF/BLEU(형태소)/NER 비교표 + 개선폭 출력. |
| `sample_compare.py` | **샘플 5개 번역 비교.** random.seed(7)로 공통 완료 ID 중 5개를 뽑아 원문·정답·baseline·few·v4 나란히 출력. |
| `show_prompt.py` | **AISO 선택 예시 프롬프트 확인.** 샘플 쿼리 1개에 대해 AISO가 선택한 예시와 패턴·길이 버킷을 출력. |
| `make_pptx.py` | **발표 PPTX 자동 생성.** python-pptx로 4단계 실험 결과를 네이비·골드 색상 테마의 PPTX 슬라이드로 자동 생성. |
| `fewshot_config.json` | **Few-shot 고정 설정.** 최적 5개 예시 문장과 프롬프트 템플릿 저장. |
| `aiso_fewshot_guide.ipynb` | **AISO few-shot 가이드 노트북.** AISO 기반 동적 예시 선택 과정을 단계별로 설명. |
| `aiso_fewshot_selector.ipynb` | **AISO few-shot 선택기 노트북.** 실제 코퍼스에서 AISO로 예시를 선택하는 실험. |
| `eval300_sampling_report.md` | **300개 층화 샘플링 보고서.** 길이 버킷(XS/S/M/L) × 문체 패턴(GEN/REP/DEN/MEM/ROY) KL divergence 검증 결과. |
| `report_말모이.md` | **5차 최종 실험 보고서.** ETS 지표 도입 배경(NER Recall closed loop 문제), SJW HTML 독립 소스 정답지 구축, 4단계 전략 전체 결과 정리. |

---

## 05_eval_assets — 평가 파이프라인 구축

| 파일 | 설명 |
|------|------|
| `make_eval_set.py` | **eval_set_1925 구성.** `Merged_Corpus_Final.json` 3000개 샘플에서 Gemma BLEU ≥ 20 필터 + reference 중복 제거로 대표 후보 1925개 구성. |
| `build_ner_groundtruth.py` | **NER 정답지 생성 (1925개).** `ddokbaro/SillokBert-NER` 모델로 원문 개체명 추출 → `inverted_index_injo`·`person_master`로 한자→한글명 변환 → `ner_groundtruth.json` 저장. |
| `build_ner_groundtruth_300.py` | **NER 정답지 생성 (300개).** 기존 `ner_groundtruth.json`에서 겹치는 ID 재활용, 나머지만 SillokBERT-NER 새로 추론. |
| `build_fewshot_prompt.py` | **Few-shot 프롬프트 구성.** SJW U0(영조 시기) XML에서 20~150자, 한자 비율 <10% 번역문을 수집 → random.seed(42)로 5개 선택 → 프롬프트 템플릿 조립. |
| `build_expression_dict.py` | **고전 어투 표현 사전 구축.** `SJW_Corpus_Final` 전체 번역문에서 "보고/아룀", "명령/하교", "임명/제수" 등 12개 의미 그룹별 표현 빈도를 집계해 `expression_dict.json` 생성. |
| `build_sjw_expr_index.py` | **SJW 표현 역색인 구축.** 11개 핵심 표현(아뢰기를·전교하기를·윤허하다 등)을 SJW 코퍼스에서 검색, 패턴 매칭 주변 80자 예문 추출 → `sjw_expr_index.json` 저장. |
| `eval_fewshot_gemma.py` | **Gemma few-shot 번역 실행 (eval_assets 기반).** `eval_set_1925.json` 전체를 `fewshot_config.json` 예시로 번역, `results_fewshot_gemma.jsonl` 출력. |
| `eval_expr_injection.py` | **어투 사전 주입 실험 v1.** 원문 한문 패턴(啓曰→"아뢰기를", 傳敎→"전교하기를" 등) 감지 후 관련 카테고리 표현을 "참고하여" 수준으로 주입. 100자 이상 629개 대상. |
| `eval_expr_injection_v2.py` | **어투 주입 v2 (강제 주입).** 패턴 → 표현 1:1 직접 매핑으로 "반드시 사용하세요" 강제 지시. 가장 강한 1개 패턴만 주입. |
| `eval_expr_injection_v3.py` | **어투 주입 v3 (few-shot + 표현 결합).** few-shot 5예시 + 아뢰기를 제외 표현 주입 + SJW 용례 + 부정 예시("임명하다 X") 결합. |
| `eval300_v4_1925.py` | **v4 전략 300개 번역 (최신 버전).** eval300_1925.json 기준, 3개 API 키 라운드로빈으로 v4 프롬프트 번역. |
| `eval_v4.py` | **v4 프롬프트 극치 실험 (eval_set 기반).** 역할 지정 + 번역 원칙 + 과잉억제 규칙 + 8개 다양 예시 + 패턴 조건부 표현 주입. 100자 이상 대상. |
| `score_baseline_4metrics.py` | **Baseline 4지표 채점.** `bleu_results_gemma4_26b.jsonl`에서 `eval_set_1925` ID 교집합 필터링 후 BLEU(char)/chrF/BLEU(형태소)/chrF(형태소) 산출, `baseline_4metrics.json` 저장. |
| `score_fewshot.py` | **Few-shot 4지표 채점.** `results_fewshot_gemma.jsonl` 기준 BLEU(char)/chrF/BLEU(형태소)/chrF(형태소). baseline 결과(34.98)와 비교표 출력. |
| `score_long629.py` | **5-way ablation 629개 채점.** 100자 이상 629개 eval set 대상 baseline/few-shot/expr-injection v1·v3/kb-inject/combined 6개 조건 비교. |
| `ner_eval_set.py` | **SillokBERT-NER eval 태깅.** `ddokbaro/SillokBert-NER`로 `eval_set_1925` 전체 원문 태깅 → PER/LOC/POH/DAT 태그별 빈도 통계 + `ner_results.jsonl` 저장. |
| `ner_entity_recall.py` | **NER entity recall 측정 (SillokBERT 기반).** SillokBERT-NER로 원문 한자 개체명 추출 → `inverted_index_injo`로 한글명 변환 → baseline/few-shot hypothesis에서 존재 여부 확인, 태그별 세부 recall 출력. |
| `analyze_bleu.py` | **BLEU 분포 통계.** 전체 결과 BLEU 점수 분포: 평균·표준편차·중앙값·백분위수(5~95) + IQR/Z-score 기반 이상치 경계값 산출. |
| `analyze_low_bleu.py` | **저BLEU 케이스 원인 분석.** baseline·few-shot 둘 다 평균 < 25인 케이스를 추출해 원문 패턴(길이·한자 종류) 분류 출력. |
| `sentence_bleu_dist.py` | **문장단위 BLEU 분포 비교.** baseline·few-shot 각 문장의 BLEU를 계산, 차이(diff) 기준 정렬 → `sentence_bleu_results.json` 저장. |
| `make_comparison.py` | **baseline vs v4 번역 비교 텍스트.** 원문·정답·baseline·v4 나란히 출력. |
| `make_comparison_fewshot.py` | **baseline vs few-shot 비교 텍스트.** 교집합 ID에 대해 원문·정답·baseline·fewshot 4열 비교 파일 생성. |

---

## 06_NER — 개체명 인식 및 인명 정답지 구축

| 파일 | 설명 |
|------|------|
| `build_groundtruth.py` | **SJW HTML 크롤링 기반 ETS 정답지 구축 (5차 핵심).** `fetch_sjw_raw.go`로 수집한 HTML에서 `<span class="idx_person">` 태그로 한자 인명 추출 → SmartProxy로 직접 크롤링 → `inverted_index_injo`·`person_master`로 한글명 매핑, KB 미등재 시 `hanja` 라이브러리 음독 변환. 이어받기 기능 포함. |
| `run_ner.py` | **KB 기반 인명 후보 추출기.** `ahocorasick` 자동화로 `inverted_index_injo/jeongjo` 표면형을 원문에서 고속 검색 → 인물 ID → `person_master`에서 메타데이터(본명·자·호·관직·생몰 연도) 조회. |

---

## data — 소형 데이터 파일

| 파일 | 크기 | 설명 |
|------|------|------|
| `eval_set_1925.json` | 2.2 MB | 층화 샘플링 후보 1,925개 (전체 코퍼스 대표 셋) |
| `eval300_1925.json` | 307 KB | 1,925개 중 최종 선택 300개 평가셋 |
| `fewshot_config.json` | 2 KB | Few-shot 고정 예시 5개·프롬프트 템플릿 |
| `ner_groundtruth_300.json` | 44 KB | 300개 ETS 정답지 — SJW HTML `<span class="idx_person">` 태그 기반 독립 구축 |
| `sjw_raw_300.json` | 31 KB | 평가셋 300개 원문 HTML 수집 결과 |
| `inverted_index_injo.json` | 433 KB | 인조 시기 인물 역색인 (한자명·자·호·약칭 → 인물 ID) |
| `id_lookup_injo.json` | 1.5 MB | 인조 시기 인물 ID → 관직 이력·활동 연도 상세 사전 (동명이인 필터링용) |

---

## 최종 실험 결과 (5차 기준 — ETS 지표)

> **ETS (Entity Translation Score)**: NER Recall의 closed loop 문제를 해소하기 위해 5차에서 도입.  
> SJW 사이트 HTML(`<span class="idx_person">`) 독립 소스 정답지로 측정.  
> NERinject의 NER Recall = 1.000 vs ETS = 0.888 → closed loop로 인한 수치 부풀림 제거.

| 전략 | BLEU(c) | chrF | BLEU(형태소) | ETS |
|------|---------|------|------------|-----|
| Baseline | 35.51 | 30.72 | 27.35 | 0.744 |
| Few-shot | 39.46 | 34.27 | 31.90 | 0.732 |
| Few + NERfix | 39.78 | 34.69 | 32.19 | 0.825 |
| **Few + NERinject** | **40.61** | **35.17** | **33.09** | **0.888** |

**핵심 교훈:**
- Few-shot: BLEU +3.95p, ETS −0.012 → 문체 일치와 인명 정확도는 트레이드오프
- NERfix: ETS +0.093p → 오독 교정 효과 명확, 생략 오류는 한계
- NERinject: ETS +0.063p → 번역 전 인명 주입이 생략·오독 동시 방지
- ETS 0.888 천장 → KB 미등재 인명 주입 불가에서 기인
