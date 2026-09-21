#!/usr/bin/env python3
"""모델 탐침 — 골든셋 60 배치 1건으로 한 모델의 quota(429 quotaValue)·지연·실패 분류·품질을 한 번에 읽는다 (M4-S2 ①).

M3-S5에서 flash-lite RPD 500 / RPM 15를 확정한 방법 그대로다: 워커의 적응형 리미터가 20 RPM에서 출발해 올라가다
provider의 429를 받으면, 그 본문의 `quotaId`/`quotaValue`가 한도를 알려준다. 문서 값이 아니라 응답 본문이 정본이다(원칙 4).
RPD는 소진해야만 보이므로 이 탐침으로는 안 나온다 — 미실측이면 미실측으로 둔다.

전제: 워커가 그 모델로 떠 있다 (PROMPT_TEMPLATE 미지정 = 생산 프롬프트, 캐시 off, 승격 off):
  GEMINI_MODEL=gemma-4-26b-a4b-it CACHE_L1_ENABLED=false CACHE_L2_ENABLED=false TIER_UP_ENABLED=false \\
    docker compose -f deploy/docker-compose.yml up -d --no-deps worker
사용: uv run --with sacrebleu --with "psycopg[binary]" python eval/probe_model.py --model gemma-4-26b-a4b-it [--n 60] [--max-minutes 25]
결과: eval/probe_<model>.json + 표준출력 요약. 배치가 max-minutes를 넘기면 pause하고 그때까지의 결과를 낸다.
"""
import argparse
import collections
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prompt_ablation as pa
import score_db

QUOTA_RX = re.compile(r"quotaId: ([A-Za-z-]+).*?quotaValue: (\d+)", re.S)


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--max-minutes", type=float, default=25)
    ap.add_argument("--batch-id", help="이미 제출된 배치를 이어서 기다리고 요약 (드라이버가 죽었을 때)")
    a = ap.parse_args()
    import psycopg

    env = sh("docker exec sjw-worker env")
    if f"GEMINI_MODEL={a.model}" not in env:
        sys.exit(f"워커가 {a.model}로 떠 있지 않다:\n" + "\n".join(l for l in env.splitlines() if l.startswith(("GEMINI_MODEL", "PROMPT_TEMPLATE", "CACHE_L1"))))
    log_mark = 0 if a.batch_id else int(sh("docker logs sjw-worker 2>&1 | wc -l").strip() or 0)
    t0 = time.monotonic()
    started = datetime.now(timezone.utc)
    if a.batch_id:
        batch_id = a.batch_id
        print(f"[{a.model}] batch {batch_id} 이어서 대기 (로그는 워커 기동 이후 전체를 본다)")
    else:
        batch_id = pa.submit_batch(a.n)
        print(f"[{a.model}] batch {batch_id} 제출 ({a.n}건, 예산 {2 * a.n})")

    status = None
    while True:
        code, b = pa.http("GET", f"/api/v1/batches/{batch_id}")
        status = b["status"]
        print(f"    {status} {b['done']}/{b['total']} 실패 {b['failed']}  {int(time.monotonic() - t0)}s", end="\r", flush=True)
        if status in ("COMPLETED", "BUDGET_EXHAUSTED", "QUOTA_PAUSED", "PAUSED"):
            break
        if (time.monotonic() - t0) / 60 > a.max_minutes:
            pa.http("POST", f"/api/v1/batches/{batch_id}/pause")
            status = "PAUSED(max-minutes)"
            break
        time.sleep(10)
    print()
    wall = time.monotonic() - t0

    logs = "\n".join(sh("docker logs sjw-worker 2>&1").splitlines()[log_mark:])
    quota = collections.Counter(QUOTA_RX.findall(logs))
    n429 = logs.count("429")
    feedback = [l.split("AdaptiveRateLimiter    : ")[-1] for l in logs.splitlines() if "429 피드백" in l]

    with psycopg.connect(score_db.DSN) as conn:
        rows = conn.execute("""SELECT status, error_class, quality_grade, model_used, tokens_in, tokens_out,
                                      EXTRACT(EPOCH FROM (completed_at - created_at))
                               FROM translation_job WHERE batch_id = %s::uuid""", (batch_id,)).fetchall()
        gold = score_db.load_goldenset(pa.SAMPLE_PATH)
        gt = score_db.load_groundtruth(pa.GROUNDTRUTH_PATH)
        found = score_db.fetch_results(conn, gold.keys(), batch_ids=[batch_id], model=a.model)
    by_status = collections.Counter((r[0], r[1]) for r in rows)
    grades = collections.Counter(r[2] for r in rows if r[0] == "SUCCEEDED")
    tin = [r[4] for r in rows if r[4]]
    tout = [r[5] for r in rows if r[5]]
    items = [{"id": gold[h]["id"], "reference": gold[h]["reference"], "hypothesis": r["hypothesis"],
              "entities": r["entities"], "tokens_in": r["tokens_in"], "grade": r["grade"]} for h, r in found.items()]
    scores = None
    if len(items) >= score_db.MIN_ITEMS:
        sc = score_db.score_items(items, gt)
        scores = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in sc.items() if not k.startswith("_")}

    out = {
        "model": a.model, "batch_id": batch_id, "n": a.n, "started": started.isoformat(timespec="seconds"),
        "final_status": status, "wall_seconds": round(wall), "jobs_per_min": round(60 * sum(1 for r in rows if r[0] == "SUCCEEDED") / wall, 1) if wall else None,
        "job_status": {f"{s}{'/' + e if e else ''}": c for (s, e), c in by_status.items()},
        "grades": dict(grades),
        "quota_429": {f"{qid}={val}": c for (qid, val), c in quota.items()},   # 정본: 429 본문의 quotaId/quotaValue
        "n_429_log_lines": n429, "limiter_feedback": feedback[:10],
        "tokens_in_mean": round(statistics.fmean(tin), 1) if tin else None,
        "tokens_out_mean": round(statistics.fmean(tout), 1) if tout else None,
        "scores": scores,
    }
    path = HERE / f"probe_{a.model}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "limiter_feedback"}, ensure_ascii=False, indent=1))
    for f in feedback[:6]:
        print("  ", f)
    print(f"저장: {path.name}")


if __name__ == "__main__":
    main()
