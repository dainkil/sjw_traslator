#!/usr/bin/env python3
"""승정원일기 잔여 코퍼스 완역 비용/시간 모델 (M0).

모든 수치는 파라미터다. 기본값의 출처는 각 help 문자열에 [실측]/[공시가]/[추정]으로 표기한다.
[추정] 파라미터는 M1(countTokens, 지연 실측)·M2(배치 실측)에서 실측치로 교체한다.

사용:
  python cost_model.py                          # 기본 시나리오
  python cost_model.py --cache-hit-rate 0.4     # 가정 변경 재계산
  python cost_model.py --batch-discount --model flash-lite
"""
import argparse
from dataclasses import dataclass, fields


PRICES_USD_PER_MTOK = {
    # [공시가] 2026-08-31 확인, Gemini Developer API 기준
    # https://devtk.ai/en/models/gemini-2-5-flash/ 외
    "flash":      {"in": 0.30, "out": 2.50},
    "flash-lite": {"in": 0.10, "out": 0.40},  # 2.5-flash-lite 단종 확인(2026-08-31) — 저가 티어 참고용
}


@dataclass
class Params:
    # --- 코퍼스 규모 ---
    total_corpus_chars: float = 242_500_000  # [선행 README] 승정원일기 총 글자 수
    translated_ratio: float = 0.374          # [선행 README] 국역 완료율
    # --- 문장 통계: malmoi/Merged_Corpus_Final.json 62,476쌍 [실측 2026-08-31] ---
    avg_src_chars_per_sentence: float = 126.1  # [실측] 원문(한문) 평균 글자 수
    out_per_src_char_ratio: float = 2.114      # [실측] 한국어 번역문/한문 원문 길이비
    # --- 토큰 환산 [실측 2026-08-31 — countTokens, 골든셋 300문장, measure_tokens.py] ---
    tokens_per_src_char: float = 0.954   # [실측] 한자 원문 토큰/글자 (중앙값 0.940)
    tokens_per_out_char: float = 0.630   # [실측] 한국어 번역문 토큰/글자 (중앙값 0.621)
    prompt_overhead_tokens: float = 448  # [실측] 페르소나 고정부. KB블록 주입분은 미포함(문장별 가변, 추정 +50~150)
    # --- 운영 가정 ---
    retry_overhead: float = 0.05   # [추정] 재시도로 인한 호출량 증가율 (429/5xx)
    cache_hit_rate: float = 0.0    # M3 전 기준. 실측 후 갱신
    # --- 단가/환율 ---
    model: str = "flash"
    batch_discount: bool = False   # [공시가] Batch API 50% 할인
    usd_krw: float = 1400.0        # [추정] 환율
    # --- 무료 티어 (ADR-016) ---
    free_tier: bool = False           # True면 비용 0, RPD cap이 벽시계를 지배
    requests_per_day_cap: float = 0   # 일일 무료 요청 한도 (0=무제한). 새 키 발급 후 실측 기입
    # --- 처리 시간 ---
    concurrency: int = 50          # 외부 API 동시성 상한 (설계 변수)
    avg_call_latency_s: float = 2.0  # [추정 — M1 실측으로 교체] LLM 호출 왕복


def run(p: Params) -> dict:
    remaining_chars = p.total_corpus_chars * (1 - p.translated_ratio)
    sentences = remaining_chars / p.avg_src_chars_per_sentence
    llm_sentences = sentences * (1 - p.cache_hit_rate)
    calls = llm_sentences * (1 + p.retry_overhead)

    tokens_in_per_call = p.avg_src_chars_per_sentence * p.tokens_per_src_char + p.prompt_overhead_tokens
    tokens_out_per_call = p.avg_src_chars_per_sentence * p.out_per_src_char_ratio * p.tokens_per_out_char
    tokens_in = calls * tokens_in_per_call
    tokens_out = calls * tokens_out_per_call

    price = PRICES_USD_PER_MTOK[p.model]
    disc = 0.5 if p.batch_discount else 1.0
    cost_usd = (tokens_in / 1e6 * price["in"] + tokens_out / 1e6 * price["out"]) * disc
    if p.free_tier:
        cost_usd = 0.0
    cost_krw = cost_usd * p.usd_krw

    wall_days = calls * p.avg_call_latency_s / p.concurrency / 86400
    if p.requests_per_day_cap > 0:
        wall_days = max(wall_days, calls / p.requests_per_day_cap)
    return {
        "잔여 글자 수": remaining_chars,
        "잔여 문장 수": sentences,
        "LLM 호출 수 (캐시·재시도 반영)": calls,
        "입력 토큰 (총)": tokens_in,
        "출력 토큰 (총)": tokens_out,
        "총 비용 (USD)": cost_usd,
        "총 비용 (KRW)": cost_krw,
        "문장당 비용 (KRW)": cost_krw / sentences,
        "벽시계 시간 (일)": wall_days,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for f in fields(Params):
        arg = "--" + f.name.replace("_", "-")
        if f.type in (bool, "bool"):
            ap.add_argument(arg, action="store_true")
        elif f.name == "model":
            ap.add_argument(arg, choices=PRICES_USD_PER_MTOK, default=f.default)
        else:
            ap.add_argument(arg, type=type(f.default), default=f.default)
    args = ap.parse_args()
    p = Params(**vars(args))

    print(f"# 시나리오: model={p.model} batch={p.batch_discount} cache={p.cache_hit_rate:.0%} "
          f"concurrency={p.concurrency}\n")
    for k, v in run(p).items():
        print(f"{k:28s} {v:>18,.1f}")
    print("\n[주의] 토큰 환산은 실측(2026-08-31). 지연·환율·재시도율은 (추정) — M1/M2 실측 후 갱신.")


if __name__ == "__main__":
    main()
