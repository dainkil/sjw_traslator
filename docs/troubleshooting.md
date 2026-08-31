# 트러블슈팅 — 실제로 밟은 함정 기록

## 1. Spring AI google-genai: `project-id`/`location` 설정 시 Vertex 모드 전환

Developer API(키 인증)를 쓸 때 `spring.ai.google.genai.project-id` 또는 `location` 프로퍼티가 존재하면 클라이언트가 Vertex AI 모드로 전환되어 **API 키가 400 인증 오류로 거부**된다.

**대응:** `api-key`만 설정한다. `api/src/main/resources/application.yml`에 경고 주석으로 명시해 뒀다. (사전 조사로 확인, 계획서 §4.3)

## 2. `429 ... exceeded its monthly spending cap` — rate limit이 아니다 (2026-08-31 실제 발생)

M1 첫 E2E 호출에서 발생:

```
com.google.genai.errors.ClientException: 429 . Your project has exceeded its
monthly spending cap. Please go to AI Studio at https://ai.studio/spend ...
```

- HTTP 코드는 429지만 **분당 rate limit(RPM)이 아니라 프로젝트 월 지출 상한 초과**다. AI Studio → Spend에서 상한을 올리거나 결제를 활성화해야 하며, 재시도·백오프로는 절대 해소되지 않는다.
- Spring AI 내장 RetryTemplate이 이 429를 재시도하는 것을 로그로 확인 — **일시 오류(rate limit)와 영구 오류(예산 소진)를 같은 코드로 주므로 응답 본문 메시지로 분류해야 한다.** M2의 실패 분류(DLQ 경로) 설계에 이 케이스를 반영한다: `SPEND_CAP`은 재시도 금지, 즉시 배치 일시정지 + 운영자 알림이 옳은 처리다.
- 이 동작은 본 프로젝트의 예산 서킷브레이커(§5.3)가 Google 쪽 상한에 도달하기 *전에* 우리 쪽에서 먼저 차단해야 하는 이유이기도 하다 — Google 상한은 월 단위 전역이라 터지면 그 달 내내 전 서비스가 죽는다.
- 참고: `countTokens`는 무과금이라 지출 상한과 무관하게 동작한다 (토큰 실측은 상한 초과 상태에서도 정상 수행됨).
- **탐침 결과 (2026-08-31, 동일 키로 모델 5종 1회씩)**: `gemini-2.5-flash`·`gemini-3.1-flash-lite`·`gemma-4-26b-a4b-it` 전부 동일한 지출 상한 429 → 상한은 **프로젝트 전역**이며 모델·무료티어 후한 Gemma조차 우회 불가. **결제가 연동된 프로젝트의 키는 유료 티어로 과금되므로, 무료 운영(ADR-016)에는 결제 미연동 프로젝트에서 발급한 키를 써야 한다.** 부수 확인: `gemini-2.5-flash-lite`는 단종(404 "no longer available"), `gemma-3-27b-it` 제거됨.

## 3. `.env.example`이 `.env.*` gitignore 패턴에 걸림

`.env`를 막으려고 `.env.*`를 넣으면 견본 파일까지 무시된다. `!.env.example` 예외를 추가할 것.
