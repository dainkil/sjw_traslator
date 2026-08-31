"""
score_300.py — 번역 결과 평가 스크립트
지표: BLEU(char), chrF, BLEU(m), NER recall
breakdown: 패턴별 / 길이 버킷별 / 엔티티 보유 여부별

사용법:
  python score_300.py results300_fixed_kbinject.jsonl
  python score_300.py results300_fixed_kbinject.jsonl --detailed
"""

import json
import re
import sys
import argparse
from pathlib import Path
from collections import defaultdict

try:
    import sacrebleu
except ImportError:
    print("sacrebleu 미설치. 실행: pip install sacrebleu", file=sys.stderr)
    sys.exit(1)


# ── 패턴 감지 ─────────────────────────────────────────────────────
PATTERN_RULES = [
    ("REP", re.compile(r"啓曰")),
    ("DEN", re.compile(r"不許")),
    ("MEM", re.compile(r"狀啓")),
    ("ROY", re.compile(r"上曰|傳曰")),
]

def detect_pattern(original: str) -> str:
    for name, pat in PATTERN_RULES:
        if pat.search(original):
            return name
    return "GEN"


# ── 길이 버킷 ─────────────────────────────────────────────────────
def length_bucket(original: str) -> str:
    n = len(original)
    if n <= 30:   return "XS"
    if n <= 80:   return "S"
    if n <= 150:  return "M"
    return "L"


# ── NER recall ────────────────────────────────────────────────────
def ner_recall_for_item(entities: list, hypothesis: str) -> float | None:
    """해당 샘플의 NER recall. 엔티티 없으면 None."""
    per_entities = [e for e in entities if e[0] == "PER"]
    if not per_entities:
        return None
    hits = sum(1 for _, _, hangul in per_entities if hangul in hypothesis)
    return hits / len(per_entities)


# ── 지표 계산 ─────────────────────────────────────────────────────
def compute_bleu_char(hypotheses: list[str], references: list[str]) -> float:
    result = sacrebleu.corpus_bleu(
        hypotheses,
        [references],
        tokenize="char",
    )
    return result.score


def compute_chrf(hypotheses: list[str], references: list[str]) -> float:
    result = sacrebleu.corpus_chrf(hypotheses, [references])
    return result.score


def compute_bleu_m(hypotheses: list[str], references: list[str]) -> float:
    """BLEU(m): 어절(공백) 기준 tokenize='none' 사용."""
    result = sacrebleu.corpus_bleu(
        hypotheses,
        [references],
        tokenize="none",
    )
    return result.score


# ── 그룹별 출력 ───────────────────────────────────────────────────
def print_group_results(label: str, group: list[dict]):
    if not group:
        return
    hyps = [r["hypothesis"] for r in group]
    refs = [r["reference"]  for r in group]

    bleu_c = compute_bleu_char(hyps, refs)
    chrf   = compute_chrf(hyps, refs)
    bleu_m = compute_bleu_m(hyps, refs)

    ner_scores = [s for r in group if (s := ner_recall_for_item(r["entities"], r["hypothesis"])) is not None]
    ner_str = f"{sum(ner_scores)/len(ner_scores)*100:.2f}" if ner_scores else "  N/A"

    print(f"  {label:<22} n={len(group):>3}  BLEU(c)={bleu_c:>6.2f}  chrF={chrf:>6.2f}  BLEU(m)={bleu_m:>6.2f}  NER={ner_str}")


# ── 메인 ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results_jsonl", help="results300_*.jsonl 경로")
    parser.add_argument("--detailed", action="store_true", help="패턴/길이별 breakdown 출력")
    args = parser.parse_args()

    results_path = Path(args.results_jsonl)
    if not results_path.exists():
        print(f"파일 없음: {results_path}", file=sys.stderr)
        sys.exit(1)

    results = []
    with open(results_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))

    print(f"\n결과 파일: {results_path.name}")
    print(f"총 샘플: {len(results)}\n")

    # ── 전체 지표 ────────────────────────────────────────────────
    hyps = [r["hypothesis"] for r in results]
    refs = [r["reference"]  for r in results]

    bleu_c = compute_bleu_char(hyps, refs)
    chrf   = compute_chrf(hyps, refs)
    bleu_m = compute_bleu_m(hyps, refs)

    ner_scores = [
        s for r in results
        if (s := ner_recall_for_item(r.get("entities", []), r["hypothesis"])) is not None
    ]
    ner_mean = sum(ner_scores) / len(ner_scores) * 100 if ner_scores else None

    print("=" * 60)
    print("전체 결과")
    print("=" * 60)
    print(f"  BLEU(char) : {bleu_c:.2f}")
    print(f"  chrF       : {chrf:.2f}")
    print(f"  BLEU(m)    : {bleu_m:.2f}")
    if ner_mean is not None:
        print(f"  NER recall : {ner_mean:.2f}  (샘플 {len(ner_scores)}/{len(results)}개)")
    else:
        print(f"  NER recall : N/A")

    if not args.detailed:
        return

    # ── 엔티티 보유 여부 breakdown ────────────────────────────────
    print("\n" + "=" * 60)
    print("엔티티 보유 여부별")
    print("=" * 60)
    with_ent    = [r for r in results if r.get("entities") or r.get("has_kb")]
    without_ent = [r for r in results if not (r.get("entities") or r.get("has_kb"))]
    print_group_results("엔티티 있음", with_ent)
    print_group_results("엔티티 없음", without_ent)

    # ── 패턴별 breakdown ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("패턴별")
    print("=" * 60)
    by_pattern = defaultdict(list)
    for r in results:
        pat = detect_pattern(r["original"])
        r["_pattern"] = pat
        by_pattern[pat].append(r)

    for pat in ["GEN", "REP", "DEN", "MEM", "ROY"]:
        print_group_results(pat, by_pattern[pat])

    # ── 길이 버킷별 breakdown ─────────────────────────────────────
    print("\n" + "=" * 60)
    print("길이 버킷별 (원문 기준)")
    print("=" * 60)
    by_len = defaultdict(list)
    for r in results:
        bucket = length_bucket(r["original"])
        by_len[bucket].append(r)

    for bucket in ["XS", "S", "M", "L"]:
        print_group_results(bucket, by_len[bucket])

    print()


if __name__ == "__main__":
    main()
