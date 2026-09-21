#!/usr/bin/env python3
"""M3.5-S2: 서빙 프롬프트 ablation — §5.4-(2) 비열등 규약을 프롬프트에 적용.

배경: 입력 토큰의 85%가 프롬프트다(docs/cost-model.md). 선행 연구는 역할 지정·번역 원칙이 효과 없다고 했는데
서빙 프롬프트에는 그대로 들어 있고, 예시의 따옴표 표기(" ")는 정답 코퍼스 관행(“ ”, 공백 없음)과 다르다.
어느 조각이 값을 하는지 **생산 코드 경로**로 잰다 — 변형은 PROMPT_TEMPLATE로 워커에 들어가고, 번역은 워커의
배치 파이프라인(NER→링킹→조립→LLM→게이트)이 만든다. 이 스크립트는 제출·대기·채점·판정만 한다.

설계 (사전 고정 — 변형 결과를 보기 전에 정한 것):
  - 표본: 골든셋 300에서 패턴×길이 층화 n=60, seed 42 — score_l2.py와 같은 층 (eval/eval60_stratified.json)
  - 라운드: 변형당 3회, 판정은 **중앙값** (LLM 비결정성 흡수 — L2 판정에서 단일 라운드 −2.20이 있었다)
  - 대조군 V0(생산 프롬프트)를 **먼저** 3라운드. ETS 허용 하락폭 = V0 라운드 간 폭(max−min)을 그 시점에 고정하고
    파일에 박는다. 변형은 그 뒤에만 채점된다 — 이 순서를 스크립트가 강제한다 (사후 임계 금지).
  - 임계: chrF −2.0 (§5.4) / 확정 인명 반영률 하락 0 (§5.4) / ETS 하락 ≤ V0 폭 (신규)
  - 결정: 통과한 변형 중 tokens_in 중앙값 최소를 채택. 통과 없음 → V0 유지("측정했고 안 바꿨다").
  - 캐시: 워커는 CACHE_L1_ENABLED=false CACHE_L2_ENABLED=false로 — 같은 프롬프트의 2·3라운드가 L1 히트로 LLM을
    건너뛰면 분산이 0이 되고, 실험 결과가 생산 캐시에 들어가서도 안 된다.
  - 모델 고정: TIER_UP_ENABLED=false. 배치 예산은 n의 2배(429 재시도 여유) — 예산은 안전장치지 측정 변수가 아니다.
  - self-check: DB 행의 prompt_version이 이 스크립트가 파일 바이트로 계산한 값(Java와 같은 SHA-256[:8])과 다르면
    배치를 pause하고 exit 2 — 워커가 다른 프롬프트로 떠 있다는 뜻이다.

절차 (재기동은 사람이, 순서·검증·채점은 스크립트가):
  0. uv run --with sacrebleu --with "psycopg[binary]" python eval/prompt_ablation.py --make-sample
  1. ...                                                       --dry-run     # 기대 prompt_version, 호출 수
  2. 이미지 재빌드 + api를 골든셋 60으로:
       SJW_EVAL_CORPUS=/eval/eval60_stratified.json docker compose -f deploy/docker-compose.yml up -d --build api worker
  3. 변형마다 워커 재기동 → 실행 (V0 먼저). 캐시 off + **품질 승격 off**(TIER_UP_ENABLED=false):
       CACHE_L1_ENABLED=false CACHE_L2_ENABLED=false TIER_UP_ENABLED=false \
         docker compose -f deploy/docker-compose.yml up -d worker
       ...                                                     --variant v0
       PROMPT_TEMPLATE=file:/eval/prompts/v1-no-persona.st CACHE_L1_ENABLED=false CACHE_L2_ENABLED=false \
         TIER_UP_ENABLED=false docker compose -f deploy/docker-compose.yml up -d worker
       ...                                                     --variant v1
     승격을 끄는 이유: REJECTED 문장을 3.5-flash가 다시 번역하면 표본에 두 모델이 섞이고, 이름을 떨어뜨리는
     프롬프트일수록 상위 모델이 구제해 효과가 가려진다. 게이트 판정 자체는 그대로 돌아 라운드별 REJECTED 수가
     남는다 — 그것이 "이 프롬프트가 확정 인명을 얼마나 떨어뜨리나"의 직접 신호다. (v0 1차 시도에서 실제로
     REJECTED 1건 → 승격 1회로 예산 60이 59건에서 소진됐다 — REJECTED의 첫 라이브 자연 발생.)
  4. ...                                                       --verdict
  5. 되돌리기: docker compose -f deploy/docker-compose.yml up -d api worker   (기본 env — 캐시 on, 생산 프롬프트)
quota: 변형 6 × 3라운드 × 60 = 1,080회 (flash-lite RPD 500 → 3일). 완료된 라운드는 eval/prompt_ablation.json에
있어 다음 날 같은 명령으로 이어서 돈다. 배치가 quota로 멈추면(QUOTA_PAUSED/FAILED 잔여) 안내대로 resume 후 재실행.
종료 코드: 0 / 2 측정 불가(self-check 실패, 배치 정지, 순서 위반)
"""
import argparse
import collections
import hashlib
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import score_db                                   # 채점 함수·DSN 공유 (CLI와 같은 숫자)
from score_l2 import load_patterns, stratum       # 층화 규칙 공유 (패턴 9종+없음 × 길이 3구간)

API = "http://localhost:8080"
STATE_PATH = HERE / "prompt_ablation.json"
SAMPLE_PATH = HERE / "eval60_stratified.json"
GOLDEN_PATH = HERE / "eval300_1925.json"
GROUNDTRUTH_PATH = HERE / "ner_groundtruth_300.json"
PROMPTS_DIR = HERE / "prompts"
PROD_TEMPLATE = ROOT / "common/src/main/resources/prompts/translate-main.st"
PROD_PATTERNS = ROOT / "common/src/main/resources/prompts/positive-patterns.tsv"
CONTAINER_PROMPTS = "/eval/prompts"               # compose가 ../eval을 /eval에 마운트한다

CHRF_TOLERANCE = score_db.CHRF_TOLERANCE          # §5.4 — 여기서 다시 정하지 않는다
NAME_RECALL_TOLERANCE = score_db.NAME_RECALL_TOLERANCE
ROUNDS = 3
N = 60
SEED = 42
POLL_S = 15
TERMINAL_BAD = {"PAUSED", "QUOTA_PAUSED", "BUDGET_EXHAUSTED"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 변형 목록·기대 버전 ─────────────────────────────────────────────────

def variants():
    out = {"v0": PROD_TEMPLATE}
    for p in sorted(PROMPTS_DIR.glob("v*.st")):
        out[p.stem.split("-")[0]] = p
    return out


def expected_version(template: Path) -> str:
    """PromptAssembler.version()과 동일: "main-" + SHA-256(template ++ patterns)[:8]."""
    h = hashlib.sha256()
    h.update(template.read_bytes())
    h.update(PROD_PATTERNS.read_bytes())
    return "main-" + h.hexdigest()[:8]


def container_location(v: str, template: Path) -> str:
    return "(미지정 — classpath 기본)" if v == "v0" else f"file:{CONTAINER_PROMPTS}/{template.name}"


# ── 층화 표본 ────────────────────────────────────────────────────────────

def pick_sample(n: int, seed: int) -> dict:
    """층화 표본을 계산만 한다 (파일을 쓰지 않는다 — 재현성 테스트가 이 함수를 부른다)."""
    ev = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    rows = ev["corpus"]
    patterns = load_patterns()
    buckets = collections.defaultdict(list)
    for i, r in enumerate(rows):
        buckets[stratum(r["original"], patterns)].append(i)
    rng = random.Random(seed)
    for v in buckets.values():
        rng.shuffle(v)
    order = sorted(buckets, key=lambda k: -len(buckets[k]))
    picked, i = [], 0
    while len(picked) < n and any(buckets[k] for k in order):   # 층을 돌아가며 하나씩 — 작은 층도 대표되게
        k = order[i % len(order)]
        if buckets[k]:
            picked.append(buckets[k].pop())
        i += 1
    picked.sort()                                                # 골든셋 순서 유지 (offset/limit 계약)
    sample = [rows[i] for i in picked]
    gt = score_db.load_groundtruth(GROUNDTRUTH_PATH)
    strata = collections.Counter(stratum(r["original"], patterns) for r in sample)
    out = {
        "n": len(sample), "seed": seed, "source": GOLDEN_PATH.name, "made_at": now(),
        "strata": dict(sorted(strata.items(), key=lambda kv: -kv[1])),
        "groundtruth_sentences": sum(1 for r in sample if gt.get(r["id"])),
        "groundtruth_names": sum(len(gt.get(r["id"], [])) for r in sample),
        "ids": [r["id"] for r in sample],
        "corpus": sample,
    }
    return out


def make_sample(n: int, seed: int):
    out = pick_sample(n, seed)
    SAMPLE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"표본 저장: {SAMPLE_PATH.name} n={out['n']} 층={len(out['strata'])} "
          f"정답지 인명 {out['groundtruth_names']}건/문장 {out['groundtruth_sentences']}건")
    for k, c in out["strata"].items():
        print(f"  {c:3d}  {k}")


# ── 상태 파일 ────────────────────────────────────────────────────────────

def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"created": now(), "sample": SAMPLE_PATH.name, "n": N, "rounds": ROUNDS,
            "thresholds_fixed": {"chrf": CHRF_TOLERANCE, "confirmed_name_recall": NAME_RECALL_TOLERANCE},
            "tolerances": None, "variants": {}, "verdict": None}


def save_state(st):
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── api ─────────────────────────────────────────────────────────────────

def http(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, (json.loads(e.read().decode() or "null") if e.headers.get_content_type() == "application/json" else None)


def submit_batch(n: int) -> str:
    # 예산 = 2n: 재시도 1회까지 흡수. n으로 두면 재호출 1건에 배치가 BUDGET_EXHAUSTED로 멈춘다 (v0 1차 시도)
    code, body = http("POST", "/api/v1/batches", {"offset": 0, "limit": n, "budgetLimitCalls": 2 * n})
    if code != 202:
        print(f"배치 생성 실패 HTTP {code}: {body} — api가 SJW_EVAL_CORPUS=/eval/{SAMPLE_PATH.name}로 떠 있는지, "
              f"테넌트 일일 상한(429)인지 확인", file=sys.stderr)
        sys.exit(2)
    return body["batchId"]


def db_grades(conn, batch_id):
    """라운드의 게이트 등급·모델 분포 — 승격 off이므로 REJECTED가 그대로 남고, 모델은 한 종류여야 한다."""
    grades = dict(conn.execute(
        "SELECT quality_grade, count(*) FROM translation_job WHERE batch_id = %s::uuid AND status = 'SUCCEEDED' GROUP BY 1",
        (batch_id,)).fetchall())
    models = [r[0] for r in conn.execute(
        "SELECT DISTINCT model_used FROM translation_job WHERE batch_id = %s::uuid AND status = 'SUCCEEDED'", (batch_id,)).fetchall()]
    return {"grades": grades, "models": models}


def db_prompt_versions(conn, batch_id):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT prompt_version FROM translation_job WHERE batch_id = %s::uuid AND status = 'SUCCEEDED'",
        (batch_id,)).fetchall()]


def wait_batch(conn, batch_id: str, expected_version: str) -> dict:
    """완료까지 폴링. 첫 SUCCEEDED 행이 보이는 즉시 prompt_version self-check — 틀리면 pause 후 exit 2."""
    checked = False
    while True:
        code, b = http("GET", f"/api/v1/batches/{batch_id}")
        if code != 200:
            print(f"배치 조회 실패 HTTP {code}", file=sys.stderr)
            sys.exit(2)
        if not checked:
            seen = db_prompt_versions(conn, batch_id)
            if seen:
                checked = True
                if seen != [expected_version]:
                    http("POST", f"/api/v1/batches/{batch_id}/pause")
                    print(f"self-check 실패: DB prompt_version={seen} ≠ 기대 {expected_version} — 워커가 다른 "
                          f"프롬프트로 떠 있다. 배치 {batch_id}를 pause했다. 워커를 올바른 PROMPT_TEMPLATE로 재기동한 뒤 "
                          f"배치는 버리고(재사용 금지) 다시 실행할 것.", file=sys.stderr)
                    sys.exit(2)
                print(f"    self-check 통과: prompt_version={expected_version}")
        print(f"    {b['status']} {b['done']}/{b['total']} (실패 {b['failed']})", end="\r", flush=True)
        if b["status"] == "COMPLETED":
            print()
            return b
        if b["status"] in TERMINAL_BAD:
            print()
            print(f"배치 {batch_id} 정지: {b['status']} (done {b['done']}/{b['total']}, failed {b['failed']}). "
                  f"quota 회복 후: curl -X POST {API}/api/v1/batches/{batch_id}/resume 그리고 같은 --variant 명령 재실행 "
                  f"(진행 중 라운드를 이어서 기다린다).", file=sys.stderr)
            sys.exit(2)
        time.sleep(POLL_S)


def score_batch(conn, batch_id: str, expected_version: str) -> dict:
    gold = score_db.load_goldenset(SAMPLE_PATH)
    gt = score_db.load_groundtruth(GROUNDTRUTH_PATH)
    found = score_db.fetch_results(conn, gold.keys(), batch_ids=[batch_id])
    versions = sorted({r["prompt_version"] for r in found.values()})
    if versions != [expected_version]:
        print(f"self-check 실패(채점 시점): prompt_version={versions} ≠ {expected_version}", file=sys.stderr)
        sys.exit(2)
    items = [{"id": gold[h]["id"], "reference": gold[h]["reference"], "hypothesis": r["hypothesis"],
              "entities": r["entities"], "tokens_in": r["tokens_in"]} for h, r in found.items()]
    if len(items) < score_db.MIN_ITEMS:
        print(f"채점 불가: 매칭 {len(items)}건", file=sys.stderr)
        sys.exit(2)
    sc = score_db.score_items(items, gt)
    out = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in sc.items() if not k.startswith("_")}
    out.update(db_grades(conn, batch_id))
    if len(out["models"]) != 1:
        print(f"self-check 실패: 모델이 섞였다 {out['models']} — TIER_UP_ENABLED=false로 워커를 띄웠는지 확인", file=sys.stderr)
        sys.exit(2)
    return out


# ── 실행 ────────────────────────────────────────────────────────────────

def run_variant(v: str, rounds: int):
    import psycopg
    vs = variants()
    if v not in vs:
        print(f"모르는 변형 {v}. 가능: {list(vs)}", file=sys.stderr)
        sys.exit(2)
    if not SAMPLE_PATH.exists():
        print("표본이 없다 — --make-sample 먼저", file=sys.stderr)
        sys.exit(2)
    st = load_state()
    if v != "v0":
        v0 = st["variants"].get("v0", {}).get("rounds", [])
        if sum(r["status"] == "COMPLETED" for r in v0) < rounds or st["tolerances"] is None:
            print("순서 위반: 대조군 v0 3라운드가 끝나 tolerances가 고정된 뒤에만 변형을 채점한다 (사후 임계 금지).",
                  file=sys.stderr)
            sys.exit(2)
    template = vs[v]
    expected = expected_version(template)
    entry = st["variants"].setdefault(v, {"template": str(template.relative_to(ROOT)),
                                          "worker_env": container_location(v, template),
                                          "prompt_version": expected, "rounds": []})
    if entry["prompt_version"] != expected:
        print(f"{v}의 파일이 이전 실행 이후 바뀌었다 ({entry['prompt_version']} → {expected}). 상태 파일에서 {v}를 지우고 "
              f"처음부터 다시 돌릴 것.", file=sys.stderr)
        sys.exit(2)
    n = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["n"]
    print(f"[{v}] {template.name} → prompt_version {expected}, 워커 env: {entry['worker_env']}")

    with psycopg.connect(score_db.DSN) as conn:
        while sum(r["status"] == "COMPLETED" for r in entry["rounds"]) < rounds:
            pending = next((r for r in entry["rounds"] if r["status"] != "COMPLETED"), None)
            if pending:
                print(f"  라운드 {pending['round']} 이어서 대기 (batch {pending['batch_id']})")
                batch_id = pending["batch_id"]
                rec = pending
            else:
                batch_id = submit_batch(n)
                rec = {"round": len(entry["rounds"]) + 1, "batch_id": batch_id, "status": "RUNNING",
                       "submitted_at": now(), "completed_at": None, "scores": None}
                entry["rounds"].append(rec)
                save_state(st)
                print(f"  라운드 {rec['round']} 제출: batch {batch_id} ({n}건, 예상 LLM {n}회)")
            b = wait_batch(conn, batch_id, expected)
            rec["status"] = "COMPLETED"
            rec["completed_at"] = now()
            rec["failed"] = b["failed"]
            rec["scores"] = score_batch(conn, batch_id, expected)
            save_state(st)
            s = rec["scores"]
            print(f"  라운드 {rec['round']} 완료: n={s['n']} chrF {s['chrf']:.2f} 반영률 {s['confirmed_name_recall']:.4f} "
                  f"ETS {s['ets']:.4f} tokens_in {s['mean_tokens_in']:.1f} 등급 {s['grades']}")

    if v == "v0" and st["tolerances"] is None:
        ets_vals = [r["scores"]["ets"] for r in entry["rounds"] if r["status"] == "COMPLETED"]
        chrf_vals = [r["scores"]["chrf"] for r in entry["rounds"] if r["status"] == "COMPLETED"]
        st["tolerances"] = {
            "chrf": CHRF_TOLERANCE, "confirmed_name_recall": NAME_RECALL_TOLERANCE,
            "ets": round(max(ets_vals) - min(ets_vals), 4),
            "fixed_at": now(), "v0_ets_rounds": ets_vals, "v0_chrf_rounds": chrf_vals,
            "note": "chrF·반영률은 §5.4 고정값. ETS 허용 하락폭 = V0 3라운드 폭(max-min). 변형 채점 전에 고정됨.",
        }
        save_state(st)
        print(f"  임계 고정: ETS 허용 하락 {st['tolerances']['ets']:.4f} (V0 라운드 {ets_vals}), "
              f"chrF −{CHRF_TOLERANCE}, 반영률 −{NAME_RECALL_TOLERANCE} — 이후 변형에 적용")


def medians(entry):
    rs = [r["scores"] for r in entry["rounds"] if r["status"] == "COMPLETED"]
    if len(rs) < ROUNDS:
        return None
    return {k: statistics.median(r[k] for r in rs) for k in ("chrf", "confirmed_name_recall", "ets", "mean_tokens_in")}


def verdict():
    st = load_state()
    if st["tolerances"] is None or "v0" not in st["variants"]:
        print("v0가 끝나지 않았다", file=sys.stderr)
        sys.exit(2)
    tol = st["tolerances"]
    base = medians(st["variants"]["v0"])
    rows, passing = [], []
    print(f"{'변형':6s} {'chrF':>7s} {'Δ':>6s}  {'반영률':>7s} {'Δ':>8s}  {'ETS':>7s} {'Δ':>8s}  {'tokens':>7s} {'Δ%':>6s}  판정")
    for v, entry in sorted(st["variants"].items()):
        m = medians(entry)
        if m is None:
            print(f"{v:6s} (라운드 부족)")
            continue
        d = {k: m[k] - base[k] for k in m}
        ok = (d["chrf"] >= -tol["chrf"] and d["confirmed_name_recall"] >= -tol["confirmed_name_recall"]
              and d["ets"] >= -tol["ets"])
        tag = "대조군" if v == "v0" else ("통과" if ok else "위반")
        print(f"{v:6s} {m['chrf']:7.2f} {d['chrf']:+6.2f}  {m['confirmed_name_recall']:7.4f} {d['confirmed_name_recall']:+8.4f}  "
              f"{m['ets']:7.4f} {d['ets']:+8.4f}  {m['mean_tokens_in']:7.1f} {100*d['mean_tokens_in']/base['mean_tokens_in']:+6.1f}  {tag}")
        rows.append({"variant": v, "median": m, "delta": d, "pass": ok if v != "v0" else None})
        if v != "v0" and ok:
            passing.append((m["mean_tokens_in"], v))
    chosen = min(passing)[1] if passing else None
    unmeasured = [v for v in variants() if medians(st["variants"].get(v, {"rounds": []})) is None]
    complete = not unmeasured
    st["verdict"] = {"at": now(), "complete": complete, "unmeasured": unmeasured, "tolerances": tol, "rows": rows,
                     "chosen": chosen if complete else None, "interim_leader": chosen,
                     "rule": "통과 변형 중 tokens_in 중앙값 최소. 통과 없음 → v0 유지. 전 변형 3라운드 전에는 중간 판정."}
    save_state(st)
    label = "채택" if complete else f"중간 선두 (미측정: {', '.join(unmeasured)} — 최종 아님)"
    print(f"\n{label}: " + (f"{chosen} ({st['variants'][chosen]['template']}, {st['variants'][chosen]['prompt_version']})"
                           if chosen else "없음 — V0 유지 (측정했고 안 바꿨다)"))


def drop_batch(batch_id: str, reason: str):
    """미완료 라운드를 폐기 목록으로 옮긴다 (기록은 남긴다 — 왜 버렸는지가 결과의 일부다)."""
    st = load_state()
    for v, entry in st["variants"].items():
        for r in list(entry["rounds"]):
            if r["batch_id"] == batch_id:
                if r["status"] == "COMPLETED":
                    print("완료된 라운드는 버리지 않는다", file=sys.stderr)
                    sys.exit(2)
                entry["rounds"].remove(r)
                for i, rr in enumerate(entry["rounds"], 1):
                    rr["round"] = i
                st.setdefault("discarded", []).append({**r, "variant": v, "reason": reason, "dropped_at": now()})
                save_state(st)
                print(f"폐기: {v} batch {batch_id} — {reason}")
                return
    print("그런 batch가 없다", file=sys.stderr)
    sys.exit(2)


def table():
    """docs/benchmarks.md에 붙일 마크다운 표 — 라운드별 원자료 + 중앙값. 숫자를 손으로 옮기지 않는다."""
    st = load_state()
    base = medians(st["variants"].get("v0", {"rounds": []}))
    print("| 변형 | 파일 | prompt_version | 라운드 chrF | chrF 중앙값 (Δ) | 반영률 | ETS | tokens_in (Δ%) | 등급 V/D/R | 판정 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    tol = st.get("tolerances") or {}
    for v, entry in sorted(st["variants"].items()):
        rs = [r["scores"] for r in entry["rounds"] if r["status"] == "COMPLETED"]
        m = medians(entry)
        chrfs = " / ".join(f"{r['chrf']:.2f}" for r in rs) or "—"
        if m is None or base is None:
            print(f"| {v} | `{Path(entry['template']).name}` | `{entry['prompt_version']}` | {chrfs} | (라운드 {len(rs)}/{ROUNDS}) | | | | | 미완 |")
            continue
        d = {k: m[k] - base[k] for k in m}
        g = rs[0].get("grades", {})
        grades = f"{g.get('VERIFIED', 0)}/{g.get('DEGRADED', 0)}/{g.get('REJECTED', 0)}"
        if v == "v0":
            tag = "대조군"
        else:
            ok = (d["chrf"] >= -tol.get("chrf", CHRF_TOLERANCE) and d["confirmed_name_recall"] >= -tol.get("confirmed_name_recall", 0)
                  and d["ets"] >= -tol.get("ets", 0))
            tag = "통과" if ok else "위반"
        print(f"| {v} | `{Path(entry['template']).name}` | `{entry['prompt_version']}` | {chrfs} | **{m['chrf']:.2f}** ({d['chrf']:+.2f}) "
              f"| {m['confirmed_name_recall']:.4f} ({d['confirmed_name_recall']:+.4f}) | {m['ets']:.4f} ({d['ets']:+.4f}) "
              f"| {m['mean_tokens_in']:.1f} ({100*d['mean_tokens_in']/base['mean_tokens_in']:+.1f}%) | {grades} | {tag} |")
    if st.get("discarded"):
        print()
        for r in st["discarded"]:
            print(f"- 폐기: {r['variant']} batch `{r['batch_id']}` — {r['reason']}")


def dry_run():
    vs = variants()
    n = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["n"] if SAMPLE_PATH.exists() else N
    print(f"{'변형':6s} {'파일':26s} {'chars':>5s}  {'기대 prompt_version':20s}  워커 env")
    for v, p in vs.items():
        print(f"{v:6s} {p.name:26s} {len(p.read_text(encoding='utf-8')):5d}  {expected_version(p):20s}  {container_location(v, p)}")
    calls = len(vs) * ROUNDS * n
    print(f"\n예상 LLM 호출: {len(vs)} 변형 × {ROUNDS} 라운드 × {n} = {calls}회 → flash-lite RPD 500 기준 {-(-calls // 500)}일")
    print(f"표본: {SAMPLE_PATH.name} ({'있음' if SAMPLE_PATH.exists() else '없음 — --make-sample'})")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--make-sample", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--variant", help="이 변형의 남은 라운드를 돈다 (v0 먼저)")
    g.add_argument("--verdict", action="store_true")
    g.add_argument("--drop-batch", metavar="BATCH_ID", help="미완료 라운드 폐기 (--reason 필수)")
    g.add_argument("--table", action="store_true", help="benchmarks용 마크다운 표")
    ap.add_argument("--reason", help="--drop-batch 사유")
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument("--n", type=int, default=N, help="--make-sample 표본 크기")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    if a.make_sample:
        make_sample(a.n, a.seed)
    elif a.dry_run:
        dry_run()
    elif a.variant:
        run_variant(a.variant, a.rounds)
    elif a.table:
        table()
    elif a.drop_batch:
        if not a.reason:
            ap.error("--drop-batch에는 --reason이 필요하다")
        drop_batch(a.drop_batch, a.reason)
    else:
        verdict()


if __name__ == "__main__":
    main()
