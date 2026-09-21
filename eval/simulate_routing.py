#!/usr/bin/env python3
"""M4-S1: NER 비용 라우팅 신호 분포 측정 (§5.1). **LLM 호출 0회.**

계획서 §5.1의 라우팅 규칙 표는 세 줄뿐이고 빈칸이 있다 — "엔티티 0개인데 패턴도 없는 문장",
"엔티티 3개 이상인데 KB 전건 매칭인 문장"이 어느 티어인지 정해져 있지 않다. 그 빈칸의 크기를
모르고 규칙을 확정하면 라우팅이 대부분의 문장을 어디로 보내는지 모르는 채 켜는 셈이 된다.

이 스크립트는 전수 코퍼스의 **라우팅 신호를 실측**해 각 분기의 문장 수를 센다. 신호는 전부
LLM 호출 전에 이미 계산되는 값이므로(§5.1: "추가 비용이 0인 난이도 분류기") 번역 없이 측정된다.
NER 추론 결과는 `simulate_cache.py`가 만든 캐시를 재사용한다.

측정 항목 (§5.1 "신호 추출 항목"):
  엔티티 개수 / 타입 분포(PER·LOC·DAT·POH) / KB 매칭 실패 수 / 링킹 단계(SINGLE·TIME·OFFICE·
  AMBIGUOUS·MISS) / 정형문 패턴 매칭 여부

출력은 두 부분이다: ① 계획서 §5.1 원안 표를 문자 그대로 적용한 분포(UNSPECIFIED 35.87% — ADR-010의 근거)
② **채택한 규칙**(ADR-010, `TierRouter.classify` 이식)의 분포 — T0 13.02 / T1 85.15 / T2 1.83의 재현 커맨드.

사용법:
  python3 eval/simulate_routing.py --years all --ner-cache eval/.ner_cache_all.json
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from simulate_cache import (MAX_TEXT, link, normalized_hash, reign_year_to_ad)

PATTERN_FILE = ROOT / "common" / "src" / "main" / "resources" / "prompts" / "positive-patterns.tsv"
# 채택한 규칙의 T0 표지 — 프롬프트 어휘 목록과 일부러 분리된 리소스 (ADR-010 (4), TierRouter.PATTERN_RESOURCE)
FORMULAIC_FILE = ROOT / "common" / "src" / "main" / "resources" / "routing" / "formulaic-patterns.tsv"


def load_patterns(path=PATTERN_FILE):
    out = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(re.compile(line.split("\t")[0]))
    return out


def signals(text, entities, patterns, formulaic=()):
    """§5.1의 신호 추출 — 전부 LLM 호출 전에 이미 손에 있는 값이다.

    pattern   = 프롬프트 어휘 목록(positive-patterns.tsv) 매칭 — 계획서 원안 표가 쓰던 신호
    formulaic = 정형문 구조 표지(routing/formulaic-patterns.tsv) 매칭 — 채택한 규칙의 T0 신호
    """
    types = collections.Counter(e["type"] for e in entities)
    stages = collections.Counter(e["stage"] for e in entities if e["type"] == "PER")
    confirmed = sum(1 for e in entities
                    if e["type"] == "PER" and e["stage"] in ("SINGLE", "TIME", "OFFICE"))
    return {
        "n_entities": len(entities),
        "n_per": types.get("PER", 0),
        "n_loc": types.get("LOC", 0),
        "n_dat": types.get("DAT", 0),
        "n_confirmed": confirmed,
        "n_miss": stages.get("MISS", 0),
        "n_ambiguous": stages.get("AMBIGUOUS", 0),
        "pattern": any(p.search(text) for p in patterns),
        "formulaic": any(p.search(text) for p in formulaic),
        "length": len(text),
    }


def tier_plan(s):
    """계획서 §5.1 표를 문자 그대로 적용 — 빈칸은 UNSPECIFIED로 드러낸다."""
    if s["n_miss"] > 0 or s["n_ambiguous"] > 0:
        return "T2"
    if s["n_entities"] == 0 and s["pattern"]:
        return "T0"
    if 1 <= s["n_per"] <= 2 and s["n_miss"] == 0 and s["n_ambiguous"] == 0:
        return "T1"
    return "UNSPECIFIED"


def tier_adopted(s):
    """채택한 규칙 — TierRouter.classify와 같은 순서·같은 조건 (ADR-010)."""
    if s["n_ambiguous"] > 0:
        return "T2"
    if s["n_entities"] == 0 and s["formulaic"]:
        return "T0"
    return "T1"


def t1_reason(s):
    """TierRouter.describeT1과 같은 3분기 — T1은 기본값이라 '왜 T1인가'가 읽혀야 한다."""
    if s["n_miss"] > 0:
        return "KB 미등재 보유 (KB 확장 대상)"
    if s["n_per"] == 0:
        return "엔티티 0개, 정형문 표지 없음" if s["n_entities"] == 0 else "PER 없음 (LOC·DAT만)"
    return "확정 PER 보유"


def pct(n, d):
    return f"{100.0 * n / d:.2f}%" if d else "—"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="all")
    ap.add_argument("--corpus", default=str(ROOT / "malmoi" / "Merged_Corpus_Final.json"))
    ap.add_argument("--kb", default=str(ROOT / "kb"))
    ap.add_argument("--kb-name", default="injo")
    ap.add_argument("--ner-cache", default=str(ROOT / "eval" / ".ner_cache_all.json"))
    args = ap.parse_args()

    corpus = json.load(open(args.corpus))["corpus"]
    items = corpus if args.years == "all" else [
        i for i in corpus if i["date"][:3] in set(args.years.split(","))]
    items = [i for i in items if len(i["original"]) <= MAX_TEXT]
    cache = json.loads(Path(args.ner_cache).read_text())
    inv = json.load(open(Path(args.kb) / f"inverted_index_{args.kb_name}.json"))
    ids = json.load(open(Path(args.kb) / f"id_lookup_{args.kb_name}.json"))
    patterns = load_patterns()
    formulaic = load_patterns(FORMULAIC_FILE)

    missing = [i for i in items if normalized_hash(i["original"]) not in cache]
    if missing:
        sys.exit(f"NER 캐시에 {len(missing)}건이 없다 — simulate_cache.py를 먼저 돌릴 것")

    print(f"\n{'=' * 74}\nM4-S1 라우팅 신호 분포 — {args.years} {len(items):,}문장  (LLM 호출 0회)\n{'=' * 74}")

    rows = []
    for it in items:
        text = it["original"]
        year = reign_year_to_ad(it["id"]) or 10 ** 9
        ents = []
        for e in cache[normalized_hash(text)]:
            stage = None
            if e["type"] == "PER":
                stage, _ = link(e["surface"], year, text, inv, ids)
            ents.append({"type": e["type"], "stage": stage})
        rows.append(signals(text, ents, patterns, formulaic))

    n = len(rows)
    print(f"\n── 신호 분포 ──")
    for label, key in (("엔티티 0개", lambda s: s["n_entities"] == 0),
                       ("PER 0개", lambda s: s["n_per"] == 0),
                       ("정형문 패턴 매칭", lambda s: s["pattern"]),
                       ("엔티티 0개 + 패턴 O", lambda s: s["n_entities"] == 0 and s["pattern"]),
                       ("엔티티 0개 + 패턴 X", lambda s: s["n_entities"] == 0 and not s["pattern"]),
                       ("KB MISS ≥1", lambda s: s["n_miss"] > 0),
                       ("동명이인 모호 ≥1", lambda s: s["n_ambiguous"] > 0),
                       ("확정 PER 전건(MISS·모호 0) + PER≥1",
                        lambda s: s["n_per"] >= 1 and s["n_miss"] == 0 and s["n_ambiguous"] == 0)):
        c = sum(1 for s in rows if key(s))
        print(f"  {label:<34}{c:>8,}  {pct(c, n):>8}")

    print(f"\n── PER 개수 분포 ──")
    per_dist = collections.Counter(min(s["n_per"], 6) for s in rows)
    for k in sorted(per_dist):
        label = f"{k}개" if k < 6 else "6개+"
        print(f"  PER {label:<10}{per_dist[k]:>8,}  {pct(per_dist[k], n):>8}")

    print(f"\n── 링킹 단계 분포 (PER 멘션 기준) ──")
    stage_tot = collections.Counter()   # 멘션 단위
    for it in items:
        year = reign_year_to_ad(it["id"]) or 10 ** 9
        for e in cache[normalized_hash(it["original"])]:
            if e["type"] == "PER":
                st, _ = link(e["surface"], year, it["original"], inv, ids)
                stage_tot[st] += 1
    tot_m = sum(stage_tot.values())
    for k, v in stage_tot.most_common():
        print(f"  {k:<12}{v:>8,}  {pct(v, tot_m):>8}")

    print(f"\n── 계획서 §5.1 표를 문자 그대로 적용하면 ──")
    tiers = collections.Counter(tier_plan(s) for s in rows)
    for k in ("T0", "T1", "T2", "UNSPECIFIED"):
        print(f"  {k:<14}{tiers[k]:>8,}  {pct(tiers[k], n):>8}")
    print(f"\n  ⚠ UNSPECIFIED {pct(tiers['UNSPECIFIED'], n)} — 표가 정하지 않은 문장이다. 내역:")
    un = [s for s in rows if tier_plan(s) == "UNSPECIFIED"]
    for label, key in (("엔티티 0개 + 패턴 X", lambda s: s["n_entities"] == 0 and not s["pattern"]),
                       ("PER 0개인데 LOC/DAT는 있음",
                        lambda s: s["n_per"] == 0 and s["n_entities"] > 0),
                       ("PER 3개 이상 + 전건 확정", lambda s: s["n_per"] >= 3)):
        c = sum(1 for s in un if key(s))
        print(f"    {label:<32}{c:>8,}  (UNSPECIFIED 중 {pct(c, len(un))})")

    # ── quota 타당성: 난이도 분류와 모델 배정을 1:1로 묶으면 성립하는가 ──
    # 무료 RPD 실측 (429 quotaValue): flash-lite 500 / 3.5-flash 20 (docs/cost-model.md)
    RPD = {"gemini-3.1-flash-lite": 500, "gemini-3.5-flash": 20}
    print(f"\n── quota 타당성 (무료 RPD 실측 기준) ──")
    print(f"  {'분기':<30}{'문장':>9}{'배정 모델':>24}{'RPD':>6}{'소요 일수':>10}")
    plan_map = (("T0 (엔티티0+패턴)", tiers["T0"], "gemini-3.1-flash-lite"),
                ("T1 (PER 1~2 전건확정)", tiers["T1"], "gemini-3.1-flash-lite"),
                ("T2 (MISS 또는 모호)", tiers["T2"], "gemini-3.5-flash"))
    for label, cnt, model in plan_map:
        rpd = RPD[model]
        print(f"  {label:<30}{cnt:>9,}{model:>24}{rpd:>6}{cnt / rpd:>9,.0f}일")
    t2_share = tiers["T2"] / n
    print(f"\n  T2 비중 {pct(tiers['T2'], n)} vs 상위 모델 quota 몫 "
          f"{20 / (500 + 20) * 100:.1f}% (20 / 520 RPD)")
    print(f"  → T2 수요가 상위 모델 quota의 {t2_share / (20 / 520):.0f}배다. "
          f"난이도 티어를 모델에 1:1로 묶으면 성립하지 않는다.")

    # ── 상위 모델로 올릴 대상(T2) 후보 정의별 수요 vs quota ──
    # 핵심 질문: 상위 모델을 올려서 **실제로 나아지는 문장**은 무엇인가.
    #   · AMBIGUOUS = KB가 후보 ≤3을 줬고 문맥으로 고르라고 프롬프트에 넣은 상태(§7, ADR-007).
    #     고르는 일이 추론이므로 상위 모델이 더 잘할 여지가 있다.
    #   · MISS = 역색인에 아예 없는 인물. 주입할 지식이 없으므로 **모델을 올려도 그 인물에 대해
    #     아는 바가 늘지 않는다.** 상위 모델은 지식원이 아니다(ADR-006에서 RAG를 배제한 전제와 같다).
    UPPER_RPD, LOWER_RPD = 20, 500
    upper_share = UPPER_RPD / (UPPER_RPD + LOWER_RPD)
    print(f"\n── T2(상위 모델) 후보 정의별 수요 vs quota 몫 {upper_share * 100:.1f}% ──")
    print(f"  {'정의':<40}{'문장':>9}{'비중':>9}{'quota 대비':>12}")
    candidates = (
        ("계획서 원안: MISS 또는 모호", lambda s: s["n_miss"] > 0 or s["n_ambiguous"] > 0),
        ("모호만 (MISS 제외)", lambda s: s["n_ambiguous"] > 0),
        ("모호 ≥2", lambda s: s["n_ambiguous"] >= 2),
        ("MISS만", lambda s: s["n_miss"] > 0 and s["n_ambiguous"] == 0),
    )
    for label, key in candidates:
        c = sum(1 for s in rows if key(s))
        ratio = (c / n) / upper_share if upper_share else 0
        flag = "✅ 수용" if ratio <= 1.0 else f"❌ {ratio:.1f}배 초과"
        print(f"  {label:<40}{c:>9,}{pct(c, n):>9}{flag:>14}")

    # MISS는 상위 모델의 대상이 아니라 **KB 확장 작업 목록**이다 — 그 크기를 잰다
    miss_surfaces = collections.Counter()
    for it in items:
        year = reign_year_to_ad(it["id"]) or 10 ** 9
        for e in cache[normalized_hash(it["original"])]:
            if e["type"] != "PER":
                continue
            st, _ = link(e["surface"], year, it["original"], inv, ids)
            if st == "MISS":
                miss_surfaces[e["surface"]] += 1
    covered = sum(c for sfc, c in miss_surfaces.items() if c >= 10)
    top = sum(c for _, c in miss_surfaces.most_common(200))
    print(f"\n── MISS의 정체: 상위 모델 대상이 아니라 KB 확장 목록이다 ──")
    print(f"  MISS 멘션 {sum(miss_surfaces.values()):,}건이 서로 다른 표면형 {len(miss_surfaces):,}개에 몰려 있다")
    print(f"  10회 이상 등장하는 표면형만 채워도 MISS 멘션의 {pct(covered, sum(miss_surfaces.values()))} 해소")
    print(f"  상위 200개 표면형이 MISS 멘션의 {pct(top, sum(miss_surfaces.values()))}")
    print(f"  최빈 표면형: {[f'{k}({v})' for k, v in miss_surfaces.most_common(8)]}")

    # ── 채택한 규칙 (ADR-010) — TierRouter.classify 이식. 이 절이 T0 13.02 / T1 85.15 / T2 1.83의 재현이다 ──
    adopted = collections.Counter(tier_adopted(s) for s in rows)
    zero_ent = [s for s in rows if s["n_entities"] == 0]
    covered0 = sum(1 for s in zero_ent if s["formulaic"])
    print(f"\n── 채택한 규칙 (ADR-010: T2=모호만 / T0=엔티티0+정형문 표지 / T1=나머지) ──")
    for k in ("T0", "T1", "T2"):
        print(f"  {k:<14}{adopted[k]:>8,}  {pct(adopted[k], n):>8}")
    print(f"  UNSPECIFIED   {0:>8,}  {pct(0, n):>8}   (기본값 T1 — 미정의 구간 없음)")
    print(f"  정형문 표지({FORMULAIC_FILE.name})가 엔티티 0개 문장 {len(zero_ent):,}건 중 "
          f"{covered0:,}건을 덮는다 ({pct(covered0, len(zero_ent))}) — 어휘 목록 기준 T0 {tiers['T0']:,}건과 비교")
    print(f"  T1 사유 분해 (TierRouter.describeT1):")
    t1 = collections.Counter(t1_reason(s) for s in rows if tier_adopted(s) == "T1")
    for k, v in t1.most_common():
        print(f"    {k:<34}{v:>8,}  (T1 중 {pct(v, adopted['T1'])})")

    # 품질 기반 상향 라우팅(이미 구현됨)의 수요도 같은 축에서 본다
    REJECTED_RATE = 0.0436   # docs/benchmarks.md M3-S4 (정렬 보정 후 전수 게이트 오탐률)
    promo = int(n * REJECTED_RATE)
    print(f"\n  참고: 이미 구현된 품질 기반 상향(REJECTED→3.5-flash, tier-up-enabled 기본 true)의 수요")
    print(f"    REJECTED 실측률 {REJECTED_RATE * 100:.2f}% × {n:,} = {promo:,}건 vs RPD 20"
          f"  → {promo / 20:,.0f}일 / quota의 {promo / 20:.0f}배")
    print()


if __name__ == "__main__":
    main()
