#!/usr/bin/env python3
"""M0 (추정) 토큰 파라미터를 실측으로 교체하기 위한 측정 스크립트.

Gemini countTokens API(무과금)로 골든셋 300문장을 측정:
  - tokens_per_src_char  : 한문 원문 토큰/글자
  - tokens_per_out_char  : 한국어 번역문 토큰/글자
  - prompt_overhead_tokens: 페르소나 프롬프트 고정부 토큰

사용: uv run --with google-genai --with python-dotenv python docs/cost-model/measure_tokens.py
필요: 저장소 루트 .env에 GEMINI_API_KEY
"""
import json
import statistics as st
from pathlib import Path

from dotenv import load_dotenv
from google import genai

REPO = Path(__file__).resolve().parent.parent.parent
MODEL = "gemini-2.5-flash"

PERSONA_FIXED = """당신은 승정원일기 전문 번역가입니다. 원문 한문을 정확하고 자연스러운 현대 한국어로 번역합니다.

[번역 원칙]
1. 종결어미: -하였다 사용 (-했다 금지)
2. 왕 지칭: 상(上) 또는 전하
3. 신하 자칭: 신(臣) 또는 소신
4. 인용 형식: ~하기를, "..." 하였다
5. 관직·인명은 원문 음독

[현대어 X → 실록 문체 O]
  · 임명하다 X → 제수하다 O
  · 허락하다 X → 윤허하다 O
  · 허락하지 않다 X → 윤허하지 않다 O
  · 행차하다 X → 거둥하다 O
  · 돌아오다 / 귀환하다 X → 환궁하다 O
  · 보고하기를 (지방) X → 장계하기를 / 서계하기를 O
  · 말씀하기를 / 명령하기를 X → 전교하기를 / 하교하기를 O

[번역 예시]
- 홍문관이 아뢰기를, "정경세가 현재 상주에 있으니, 올라오도록 하유하소서." 하니, 윤허한다고 전교하였다.
- 전교하기를, "영의정 이원익에게 사관을 보내어 전유하라." 하였다.
- 봉림대군에게 처음 직임을 제수하였다.
- 심양에서 재신이 장계하기를, "이달 9일에 왕세자가 서쪽으로 행차합니다." 하였다.
- 상이 혼궁 소상제를 친히 지내기 위해 거둥하였다.
- 비변사가 서계하기를, "변경의 사정이 긴박하오니 속히 군병을 증파하소서." 하였다.
- 이날 밤에 큰 바람이 불고 우레와 번개가 쳤다.

위 원칙과 예시의 문체로 다음 한문을 번역하세요. 번역문만 출력하세요:
"""


def count(client, text):
    return client.models.count_tokens(model=MODEL, contents=text).total_tokens


def main():
    load_dotenv(REPO / ".env")
    client = genai.Client()  # GEMINI_API_KEY 자동 인식

    corpus = json.loads((REPO / "eval" / "eval300_1925.json").read_text())["corpus"]

    src_ratios, out_ratios = [], []
    for i, c in enumerate(corpus):
        src, ref = c["original"], c["reference"]
        if not src or not ref:
            continue
        src_ratios.append(count(client, src) / len(src))
        out_ratios.append(count(client, ref) / len(ref))
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(corpus)}…")

    overhead = count(client, PERSONA_FIXED)
    print(f"\n측정 결과 ({len(src_ratios)}문장, model={MODEL}):")
    print(f"tokens_per_src_char  = {st.mean(src_ratios):.3f} (중앙값 {st.median(src_ratios):.3f})")
    print(f"tokens_per_out_char  = {st.mean(out_ratios):.3f} (중앙값 {st.median(out_ratios):.3f})")
    print(f"prompt_overhead_tokens(고정부, KB블록 제외) = {overhead}")
    print("\n→ cost_model.py의 기본값과 docs/cost-model.md 표를 이 수치로 갱신할 것.")


if __name__ == "__main__":
    main()
