#!/usr/bin/env python3
"""M3-S5: L2 캐시 히트 결과의 비열등 판정 (§5.4-(2), 계획서 §10 M3 추가 기준).

L2 히트는 **LLM이 생성하지 않은 문장**이다 — 다른 문장의 번역 틀에 인명을 꽂아 만든다.
품질 증거 없이 서빙할 수 없으므로(ADR-009 배경 3) 같은 문장을 두 경로로 번역해 대조한다:

  L2 경로 : 틀 적재 문장(F)을 LLM 번역 → 템플릿화 → 히트 문장(R)에 재주입   ← 평가 대상
  대조군  : R을 전체 파이프라인(LLM)으로 직접 번역                        ← 기준
  정답    : R의 전문가 번역 (원천 병렬 코퍼스, 정렬 검증 통과분만)

**생산 코드 경로로 측정한다.** L2 결과는 이 스크립트가 아니라 실행 중인 api의
`TranslationCache.lookupL2` + `TemplateSlotter.reinject` + `QualityGate`가 만든다 —
`meta.cacheHit == "L2_TEMPLATE"`로 확인하고, 아니면 표본에서 제외한다(이식으로 근사하지 않는다).

임계 (사전 고정, §5.4-(2)):
  - chrF: 대조군 대비 -2.0 이내
  - 링크 확정 인물의 한글명 재현율: 하락 0 (동등 요구)
  - 표본: 패턴x길이 층화 n=60, 3회 반복 **중앙값** (LLM 비결정성 흡수)

전제:
  1. `python3 eval/simulate_cache.py --years all --dump-l2-pairs <path>` 로 표본 풀 생성
  2. api(:8080)가 **CACHE_L2_ENABLED=true** 로 기동 중 (판정 후 기본값 false로 되돌릴 것)
  3. LLM 호출 = 쌍당 2회 x n x 라운드 (기본 60x3 = 360회, flash-lite). 히트 조회는 0회.

사용법:
  uv run --with sacrebleu python eval/score_l2.py --pairs /tmp/l2-pairs.json
  uv run --with sacrebleu python eval/score_l2.py --rounds 1 --n 10   # 축소 리허설
종료 코드: 0 통과 / 1 비열등 위반 / 2 측정 불가
"""
import argparse
import collections
import json
import random
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import sacrebleu

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from simulate_cache import normalized_hash  # 생산 코드(TextHash)와 동일 규칙, S4에서 DB 대조 검증됨

API = "http://localhost:8080"
NER = "http://localhost:8100"
CHRF_TOLERANCE = 2.0          # score_db.py와 동일 — 임계는 §5.4가 정하고 코드는 따른다
NAME_RECALL_TOLERANCE = 0.0

PATTERN_FILE = ROOT / "common" / "src" / "main" / "resources" / "prompts" / "positive-patterns.tsv"
# 원문 길이 3구간 (코퍼스 실측: 중위 35자 / 평균 79자)
LENGTH_BUCKETS = ((0, 30, "짧음"), (30, 80, "중간"), (80, 10 ** 9, "긺"))


# ── 층화 표본 ─────────────────────────────────────────────────────────────

def load_patterns():
    out = []
    for line in PATTERN_FILE.read_text(encoding="utf-8").split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            rx = line.split("\t")[0]
            out.append((rx, re.compile(rx)))
    return out


def stratum(text, patterns):
    pat = next((rx for rx, c in patterns if c.search(text)), "(패턴 없음)")
    length = next(name for lo, hi, name in LENGTH_BUCKETS if lo <= len(text) < hi)
    return f"{pat} / {length}"


def sample_stratified(pairs, n, patterns, seed):
    """패턴x길이 층화 추출 — 층을 돌아가며 하나씩 뽑아 작은 층도 대표되게 한다."""
    buckets = collections.defaultdict(list)
    for p in pairs:
        buckets[stratum(p["hit"]["original"], patterns)].append(p)
    rng = random.Random(seed)
    for v in buckets.values():
        rng.shuffle(v)
    order = sorted(buckets, key=lambda k: -len(buckets[k]))
    picked, i = [], 0
    while len(picked) < n and any(buckets[k] for k in order):
        k = order[i % len(order)]
        if buckets[k]:
            picked.append(buckets[k].pop())
        i += 1
    return picked


# ── api / redis ──────────────────────────────────────────────────────────

# 동기 경로에는 rate limiter도 재시도도 없다 (워커만 갖고 있다 — ADR-017은 워커 범위) —
# 429가 HTTP 500으로 그대로 올라온다. 측정 도구가 그 몫을 대신 진다: 호출 간 페이싱 + 백오프 재시도.
# 실측(2026-09-11): 지속 ~17 req/min에서 분당 1건씩 429. flash-lite 유효 RPM이 그 근처다.
PACE_MS = 4500          # 호출 간 간격 — 2회/쌍이므로 약 13 calls/min
RETRY_ON_429 = 3
_last_call = [0.0]


def post_sync(text, year):
    for attempt in range(RETRY_ON_429 + 1):
        wait = PACE_MS / 1000 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.monotonic()
        req = urllib.request.Request(f"{API}/api/v1/translations/sync",
                                     data=json.dumps({"text": text, "year": year}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            # 동기 경로는 429를 분류하지 않고 500으로 감싼다 — 본문에서 식별한다
            if attempt < RETRY_ON_429 and (e.code == 429 or "429" in body or "quota" in body.lower()):
                time.sleep(20 * (attempt + 1))      # provider quota 회복 대기
                continue
            raise


def post_sync_nopace(text, year):
    """캐시 히트 확인용 — LLM을 쓰지 않으므로 페이싱 대상이 아니다."""
    req = urllib.request.Request(f"{API}/api/v1/translations/sync",
                                 data=json.dumps({"text": text, "year": year}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def redis_del(keys):
    subprocess.run(["docker", "exec", "sjw-redis", "redis-cli", "DEL", *keys],
                   capture_output=True, timeout=30)


def resolve_version_segment():
    """캐시 키의 파이프라인 버전 세그먼트 — 정확한 키를 지우기 위해 필요하다."""
    probe = post_sync("傳曰知道", 1623)          # 짧은 정형문 1건 (캐시 히트일 수도 있다)
    kb, prompt = probe["meta"]["kbVersion"], probe["meta"]["promptVersion"]
    with urllib.request.urlopen(f"{NER}/healthz", timeout=30) as r:
        ner = json.load(r)["model_version"]
    env = subprocess.run(["docker", "exec", "sjw-api", "env"],
                         capture_output=True, text=True, timeout=30).stdout
    epoch = next((l.split("=", 1)[1] for l in env.split("\n")
                  if l.startswith("CACHE_EPOCH=")), "1")
    return f"{kb}:{prompt}:{ner}:{epoch}"


def reign_year(doc_id):
    try:
        if doc_id[4] == "A":
            return 1623 + int(doc_id[5:7]) - 1
    except (IndexError, ValueError):
        pass
    return None


# ── 지표 ────────────────────────────────────────────────────────────────

def name_recall(items):
    """링크 확정 인물의 한글명 반영률. score_db.py와 동일한 엄격 규칙 — 전체형 포함만 인정."""
    hits = total = 0
    for hyp, entities in items:
        for e in entities:
            if e.get("kbId") and e.get("resolvedName"):
                total += 1
                if e["resolvedName"] in hyp:
                    hits += 1
    return (hits / total if total else float("nan")), total


# ── 한 라운드 ────────────────────────────────────────────────────────────

def run_round(picked, seg, verbose, target=None):
    l2_items, base_items, refs = [], [], []
    dropped = collections.Counter()
    for i, p in enumerate(picked, 1):
        F, R = p["first"], p["hit"]
        fk = f"cache:l1:{seg}:{normalized_hash(F['original'])}"
        rk = f"cache:l1:{seg}:{normalized_hash(R['original'])}"
        tk = f"cache:l2:{seg}:{p['template_hash']}"
        try:
            redis_del([fk, rk, tk])                       # 깨끗한 상태에서 시작
            post_sync(F["original"], reign_year(F["id"]))  # ① F: LLM 번역 → 틀 적재 (LLM 1회)
            hit = post_sync_nopace(R["original"], reign_year(R["id"]))  # ② R: L2 히트 기대 (LLM 0회)
            if hit["meta"].get("cacheHit") != "L2_TEMPLATE":
                # F가 VERIFIED가 아니었거나 전체형 출현 실패 → 애초에 L2가 개입하지 않는 쌍
                dropped["L2 미개입(적재 불성립)"] += 1
                continue
            redis_del([tk, rk])                           # ③ 틀을 지우고 대조군 확보
            base = post_sync(R["original"], reign_year(R["id"]))  # (LLM 1회)
            if base["meta"].get("cacheHit"):
                dropped["대조군이 캐시로 서빙됨"] += 1
                continue
            l2_items.append((hit["translatedText"], base["entities"]))
            base_items.append((base["translatedText"], base["entities"]))
            refs.append(R["reference"])
        except urllib.error.HTTPError as e:
            dropped[f"HTTP {e.code}"] += 1
        except Exception as e:                            # 네트워크·타임아웃
            dropped[type(e).__name__] += 1
        if target and len(refs) >= target:                # 목표 도달 — 남은 호출을 아낀다
            break
        if verbose and i % 10 == 0:
            print(f"    {i}/{len(picked)} 진행 (측정 {len(refs)}건)", flush=True)

    if not refs:
        return None, dropped
    chrf_l2 = sacrebleu.corpus_chrf([h for h, _ in l2_items], [refs]).score
    chrf_base = sacrebleu.corpus_chrf([h for h, _ in base_items], [refs]).score
    rec_l2, n_conf = name_recall(l2_items)
    rec_base, _ = name_recall(base_items)
    return {"n": len(refs), "n_confirmed": n_conf,
            "chrf_l2": chrf_l2, "chrf_base": chrf_base,
            "recall_l2": rec_l2, "recall_base": rec_base}, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default="/tmp/l2-pairs.json")
    ap.add_argument("--n", type=int, default=60, help="라운드당 **측정 목표** 수 (§5.4: 60)")
    ap.add_argument("--oversample", type=float, default=1.25,
                    help="L2 미개입·인프라 실패로 빠지는 몫 보정 계수 (측정 n이 목표에 닿게)")
    ap.add_argument("--rounds", type=int, default=3, help="반복 횟수 (§5.4: 3, 중앙값)")
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--out", default=str(ROOT / "eval" / "l2_noninferiority.json"))
    args = ap.parse_args()

    pool = json.loads(Path(args.pairs).read_text())["pairs"]
    patterns = load_patterns()
    print(f"표본 풀: L2 히트 쌍 {len(pool)}건 (정렬 검증 통과분)")

    # 전제 검사 — L2가 꺼져 있으면 히트가 0건이고, 그 사유가 "적재 불성립"으로 오해된다
    env = subprocess.run(["docker", "exec", "sjw-api", "env"],
                         capture_output=True, text=True, timeout=30).stdout
    if "CACHE_L2_ENABLED=true" not in env:
        print("api가 L2 비활성 상태다 — 이 판정은 L2 히트를 측정하므로 켜고 실행해야 한다:")
        print("  CACHE_L2_ENABLED=true docker compose -f deploy/docker-compose.yml up -d api")
        print("  (판정 후 기본값 off로 되돌릴 것 — ADR-009 운영 상태)")
        sys.exit(2)

    seg = resolve_version_segment()
    print(f"파이프라인 버전: {seg}")
    print(f"층화: 패턴({len(patterns)}종+없음) x 길이 3구간, n={args.n}, {args.rounds}회 반복")
    drawn = int(args.n * args.oversample)
    print(f"추출 {drawn}건/라운드 (과표본 x{args.oversample}) → 측정 목표 {args.n}건")
    print(f"예상 LLM 호출: 최대 {drawn * args.rounds * 2}회, 페이싱 {PACE_MS}ms (히트 조회는 0회)\n")

    rounds = []
    for r in range(1, args.rounds + 1):
        picked = sample_stratified(pool, int(args.n * args.oversample), patterns, args.seed + r)
        strata = collections.Counter(stratum(p["hit"]["original"], patterns) for p in picked)
        print(f"라운드 {r}/{args.rounds} — 층 {len(strata)}개, 표본 {len(picked)}건")
        res, dropped = run_round(picked, seg, verbose=True, target=args.n)
        if res is None:
            print(f"  측정 0건 (제외: {dict(dropped)})")
            continue
        res["dropped"] = dict(dropped)
        rounds.append(res)
        print(f"  n={res['n']} (확정 인명 {res['n_confirmed']}건)  제외 {sum(dropped.values())}건 {dict(dropped)}")
        print(f"  chrF  L2 {res['chrf_l2']:.2f} vs 대조군 {res['chrf_base']:.2f}"
              f"  → {res['chrf_l2'] - res['chrf_base']:+.2f}")
        print(f"  인명  L2 {res['recall_l2']:.4f} vs 대조군 {res['recall_base']:.4f}"
              f"  → {res['recall_l2'] - res['recall_base']:+.4f}\n", flush=True)

    if not rounds:
        print("측정 불가 — 표본이 전혀 확보되지 않았다")
        sys.exit(2)

    chrf_deltas = [r["chrf_l2"] - r["chrf_base"] for r in rounds]
    rec_deltas = [r["recall_l2"] - r["recall_base"] for r in rounds]
    chrf_med, rec_med = statistics.median(chrf_deltas), statistics.median(rec_deltas)

    print("=" * 66)
    print(f"라운드 {len(rounds)}회 중앙값 판정 (§5.4 임계: chrF -{CHRF_TOLERANCE} 이내 / 인명 하락 0)")
    print(f"  chrF 차이   : {[f'{d:+.2f}' for d in chrf_deltas]} → 중앙값 {chrf_med:+.2f}")
    print(f"  인명 재현율 : {[f'{d:+.4f}' for d in rec_deltas]} → 중앙값 {rec_med:+.4f}")

    violations = []
    if -chrf_med > CHRF_TOLERANCE:
        violations.append(f"chrF 하락 {-chrf_med:.2f} > 허용 {CHRF_TOLERANCE}")
    if -rec_med > NAME_RECALL_TOLERANCE:
        violations.append(f"인명 재현율 하락 {-rec_med:.4f} > 허용 {NAME_RECALL_TOLERANCE}")

    verdict = "위반" if violations else "통과"
    Path(args.out).write_text(json.dumps({
        "date": __import__("datetime").date.today().isoformat(),
        "pipeline_version": seg, "n_per_round": args.n, "rounds": len(rounds),
        "pool_size": len(pool), "chrf_delta_median": round(chrf_med, 2),
        "name_recall_delta_median": round(rec_med, 4),
        "thresholds": {"chrf": -CHRF_TOLERANCE, "name_recall": -NAME_RECALL_TOLERANCE},
        "verdict": verdict, "per_round": rounds,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  기록: {Path(args.out).name}")

    if violations:
        print(f"\n비열등 위반: {'; '.join(violations)}")
        sys.exit(1)
    print("\n비열등 판정: 통과")


if __name__ == "__main__":
    main()
