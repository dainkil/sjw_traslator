# sjw_traslator
# 지식 주입형 언어 모델 기반 승정원일기 번역 모델 연구

<p align="center">
  <img src="https://img.shields.io/badge/Model-SillokBERT-blue" />
  <img src="https://img.shields.io/badge/LLM-Gemini_2.5_Flash-orange" />
  <img src="https://img.shields.io/badge/Task-Classical_Korean_Translation-green" />
  <img src="https://img.shields.io/badge/Status-Completed-success" />
</p>

<p align="center">
  Knowledge-Injected Language Model Pipeline for Automated Translation of Seungjeongwon Ilgi
</p>

---

## 목차

- [연구 배경](#연구-배경)
- [문제 정의](#문제-정의)
- [파이프라인 아키텍처](#파이프라인-아키텍처)
- [방법론](#방법론)
- [지식 베이스 구축](#지식-베이스-구축)
- [실험 결과](#실험-결과)
- [기술 스택](#기술-스택)
- [보고서](#보고서)
- [참고 문헌](#참고-문헌)

---

## 연구 배경

《승정원일기》는 유네스코 세계기록유산으로 등재된 세계 최대 규모의 단일 역사 기록물입니다. 인조(1623년)부터 순종(1907년)에 이르기까지 총 3,243책, 약 2억 4,250만 자에 달하는 방대한 텍스트로 구성되어 있으나, 현재 국역 완료율은 **37.4%** 에 머무르고 있으며 현재 속도를 유지할 경우 완역은 **2062년**에나 가능할 것으로 추산됩니다.

기존 AI 번역 모델(AnchiLm, SikuBERT 기반)은 BLEU 0.37~0.54의 낮은 성능에 정체되었으며, 인칭대명사·인명·관직명·지명 등 고유명사 번역 정확도는 **8.3%** 에 불과했습니다. 역사 번역에서 고유명사의 오역은 역사적 사실 자체를 왜곡하는 결과를 초래하므로, 이는 실무 도입을 가로막는 결정적 장애물이었습니다.

본 연구는 이러한 한계를 극복하기 위해 **도메인 특화 NER + 지식 베이스(KB) 연동 + 프롬프트 증강**을 결합한 지식 주입형 번역 파이프라인을 제안합니다.

---

## 문제 정의

### 기존 모델의 구조적 한계

**① 도메인 불일치**

AnchiLm, SikuBERT 등 기존 모델은 중국 고문헌인 《사고전서(四庫全書)》 기반으로 학습되었습니다. 조선 한문은 이두(吏讀) 표현·한국식 한자어·독자적 관직 및 지명 체계를 포함하고 있어, 중국 고문헌에 최적화된 모델은 조선 텍스트의 맥락을 오독할 확률이 높습니다.

**② 고유명사 환각 현상**

신경망 모델은 지식을 파라미터 내부에 암묵적으로 저장하는 구조상, 원문에서 추출한 인물이 조선의 특정 역사 인물임을 파라미터로부터 정확히 복원하는 것이 불가능에 가깝습니다. 언어 변환 능력과 팩트 검증 능력을 하나의 모델에 혼재시킨 구조적 한계에서 비롯됩니다.

---

## 파이프라인 아키텍처

기존 End-to-End 번역 방식을 탈피하여 **구문론적 언어 변환**과 **팩트 복원**을 명확히 분리한 6단계 모듈화 구조를 채택했습니다.
```
원문 입력 (승정원일기 한문)
↓
[1단계] SillokBERT 도메인 적응 (CPT + MLM)
↓
[2단계] NER 파인튜닝 — 인물(PER) / 관직(POS) / 지명(LOC) / 날짜(DAT) 추출
↓
[3단계] KB 검색 — 역색인 3단계 Fallback 구조로 후보군 추출
↓
[4단계] 엔티티 링킹 — 활동 시기 검증 + 관직 교차 검증으로 동명이인 해소
↓
[5단계] 프롬프트 증강 — 원문 + 엔티티 맥락 정보 + 번역관 페르소나 조립
↓
[6단계] Gemini 2.5 Flash 최종 번역 생성
↓
번역 출력 (KB 유/무 병렬 비교)

```
---

## 방법론

### 3.1 SillokBERT 도메인 적응 (Continued Pre-training)

기반 모델 SillokBERT-Scratch에 인조 연간 《승정원일기》 원문을 활용한 **마스크 언어 모델링(MLM)** 기반 계속 사전학습(CPT)을 수행하여 승정원일기 특유의 문체·어휘 패턴을 모델 가중치에 주입하였습니다.

| 항목 | 설정 |
|------|------|
| 기반 모델 | SillokBERT-Scratch (BERT-base-multilingual-cased) |
| 학습 코퍼스 | 인조 연간 《승정원일기》 원문 |
| 학습 방법 | MLM 기반 Continued Pre-training |
| 마스킹 비율 | 15% |
| 최적화 알고리즘 | AdamW (lr=5e-5, Cosine Decay, Warmup Ratio=0.05) |
| 실효 배치 크기 | 128 (per_device=8 × Gradient Accumulation=16) |
| 연산 정밀도 | fp16 + Gradient Checkpointing |
| 최대 시퀀스 길이 | 512 tokens |
| 연산 환경 | Google Colab A100 GPU (VRAM 40GB) |

---

### 3.2 NER 파인튜닝 (Weakly-supervised)

도메인 적응 모델에 토큰 분류 헤드를 부착하고, Silver Label 자동 생성 방식으로 학습 데이터를 구축하여 개체명 인식 모델을 파인튜닝하였습니다.

- 인식 대상: 인물(PER), 관직(POS), 지명(LOC), 날짜(DAT) — BIO 태깅 (총 9 태그)
- Silver Label 생성: SillokBERT-NER을 레이블러로 활용, 신뢰도 0.90 이상 문장만 채택
- 서브워드 정렬: `word_ids()` 활용, 첫 번째 서브워드에만 실제 레이블 부여

| 항목 | 설정 |
|------|------|
| 기반 모델 | CPT 결과물 + TokenClassification Head |
| 신뢰도 임계값 | 0.90 |
| 데이터 분할 | 학습 90% / 검증 10% (seed=42) |
| 최적화 알고리즘 | AdamW (lr=2e-5, Weight Decay=0.01, Warmup Ratio=0.1) |
| 학습 에폭 | 3 |
| 배치 크기 | 32 |
| 평가 지표 | seqeval F1 |

---

## 지식 베이스 구축

NER에서 추출된 개체를 실제 역사 인물로 연결하기 위해 인조 연간 특화 지식 베이스(KB)를 구축하였습니다.

| 파일명 | 항목 수 | 역할 | 주요 필드 |
|--------|--------|------|----------|
| `id_lookup_injo.json` | 2,690명 | 인물 메타데이터 원천 레코드 | 한글_명, 한자_명, 본관_표준, 활동_시작, 활동_종료, 관직_리스트 |
| `inverted_index_injo.json` | 9,403 키 | 멀티 키 고속 역색인 탐색 | 한자·한글 전체명, 단독 이름, 이체자 등 표기 변형 전체 |

**KB 엔티티 링킹 — 3단계 Fallback 구조**
```
1차: 표층형 전체 문자열 역인덱스 직접 조회
↓ (미매칭 시)
2차: 글자별 후보 집합 교집합 산출
↓ (미매칭 시)
3차: 개별 글자 합집합으로 후보 범위 확장
↓
최종 필터링: KB 한자명에 표층형의 모든 글자가 포함되는 후보만 통과
↓
동명이인 해소: 활동 시기 필터 → 관직 교차 검증 → 모호 케이스는 LLM에 전달
```
---

## 실험 결과

### AB 테스트 설계

- **With-KB**: NER 결과를 KB와 연결하여 인물 맥락 정보를 프롬프트에 포함
- **Without-KB**: 동일 원문을 맥락 정보 없이 번역
- 평가 대상: KB 매칭 성공 문장 100건 (random.seed=42)

### 정량 결과

| 지표 | 값 |
|------|-----|
| API 성공률 | 100% (100/100) |
| KB 차이 발생 문장 | 100/100 |
| 문장당 평균 KB 매칭 인물 수 | 2.0명 |
| 한자 병기 횟수 (With-KB) | 4,417회 |
| 한자 병기 횟수 (Without-KB) | 4,167회 (+6%) |

### 정성 분석 — KB 링킹 효과 유형

| 유형 | 원문 | Without-KB | With-KB |
|------|------|-----------|--------|
| 인명 경계 오류 방지 | 崔有後陪進 | 최유후(崔有後)로 잘못 획정 | 최유(崔有)와 後를 정확히 분리 |
| 문맥 해석 분기 | 前府院君李貴邊情事 | 邊을 '변방'으로 해석 | 邊을 별도 인명으로 태깅, 해석 분기 |
| 풀네임 복원 | 使馨長言于梧將 | 형장(馨長)으로 불완전 처리 | 이형장(李馨長)으로 성씨 복원 |

### 한계

- NER 오탐률: KB 미등록 엔티티 468개 중 111개(24%)가 인명이 아닌 표현에 PER 태그 부여
- Gemini 2.5 Flash 자체의 번역 품질이 높아 KB 연계의 차별적 기여는 인명 경계 모호·동음이의 사례에 집중

---

## 기술 스택

| 분야 | 사용 기술 |
|------|----------|
| 도메인 적응 모델 | SillokBERT-Scratch (BERT-base-multilingual-cased) |
| NER 레이블러 | SillokBERT-NER (HuggingFace) |
| 번역 LLM | Gemini 2.5 Flash (temperature=0.2) |
| 학습 방법 | MLM 기반 Continued Pre-training, Silver Label Fine-tuning |
| 평가 | seqeval (Precision / Recall / F1) |
| 연산 환경 | Google Colab A100 GPU (VRAM 40GB), fp16 + Gradient Checkpointing |

---

## 보고서

[지식_주입형_언어_모델_기반_승정원일기_번역_모델_연구.pdf](./지식_주입형_언어_모델_기반_승정원일기_번역_모델_연구.pdf)

---

## 참고 문헌

- 국사편찬위원회: https://www.history.go.kr/
- 승정원일기: https://sjw.history.go.kr/
- AnchiLm: An Effective Classical-to-Modern Chinese Translation Model. ACL Anthology, 2023. https://aclanthology.org/2023.alt-1.8/
- ddokbaro/SillokBert-NER. HuggingFace. https://huggingface.co/ddokbaro/SillokBert-NER
- Knowledge-Injected Transformer (KIT). MDPI Applied Sciences, 2026. https://www.mdpi.com/2076-3417/16/3/1601
- TranslateGemma Technical Report. arXiv:2601.09012. https://arxiv.org/abs/2601.09012
```
```
