"""
score_db.py — 골든셋 채점의 DB 어댑터 (§5.4-(2), ADR-019).

score_300.py(연구 시절 jsonl CLI)의 지표를 시스템 결과(Postgres)에 직접 붙인다.
매칭 키는 normalized_hash (TextHash.java와 동일 규칙: NFC + 공백 제거 + SHA-256).

비열등 임계 (사전 고정 — 사후에 정하면 게이트가 아니다):
  - chrF: 기준선 대비 -2.0 이내
  - 링크 확정 인물의 한글명 재현율: 하락 0 (동등 요구)

사용법:
  uv run --with sacrebleu --with "psycopg[binary]" python score_db.py            # 채점 + 기준선 비교
  uv run --with sacrebleu --with "psycopg[binary]" python score_db.py --save-baseline
기준선 파일: eval/baseline_scores.json. CI(M2.5-S8)는 종료 코드로 판정한다 (위반=1).
"""

import argparse
import hashlib
import json
import sys
import unicodedata
from datetime import date
from pathlib import Path

import psycopg
import sacrebleu

DSN = "host=localhost port=5433 dbname=sjw user=sjw password=sjw"
HERE = Path(__file__).parent
BASELINE_PATH = HERE / "baseline_scores.json"

CHRF_TOLERANCE = 2.0          # 기준선 대비 허용 하락폭
NAME_RECALL_TOLERANCE = 0.0   # 인명은 동등 요구 — 하락 0


def normalized_hash(text: str) -> str:
    normalized = "".join(unicodedata.normalize("NFC", text).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_goldenset():
    ev = json.loads((HERE / "eval300_1925.json").read_text(encoding="utf-8"))
    return {normalized_hash(r["original"]): r for r in ev["corpus"]}


def fetch_results(conn, hashes):
    """골든셋 문장과 매칭되는 최신 SUCCEEDED 결과. (hash → hypothesis, entities, model, grade)"""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (j.normalized_hash)
               j.normalized_hash, r.translated_text, r.entities, j.model_used, j.quality_grade
        FROM translation_job j
        JOIN translation_result r ON r.job_id = j.id
        WHERE j.status = 'SUCCEEDED' AND j.normalized_hash = ANY(%s)
        ORDER BY j.normalized_hash, j.completed_at DESC
        """,
        (list(hashes),),
    ).fetchall()
    return {h: {"hypothesis": t, "entities": e or [], "model": m, "grade": g}
            for h, t, e, m, g in rows}


def confirmed_name_recall(items) -> tuple[float, int]:
    """링크 확정 인물(kbId 보유)의 한글명이 번역문에 반영된 비율. (§5.4의 핵심 지표)"""
    hits = total = 0
    for it in items:
        for e in it["entities"]:
            if e.get("kbId") and e.get("resolvedName"):
                total += 1
                if e["resolvedName"] in it["hypothesis"]:
                    hits += 1
    return (hits / total if total else float("nan")), total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-baseline", action="store_true",
                        help="현재 점수를 기준선으로 저장 (모델·프롬프트 변경 확정 시에만)")
    args = parser.parse_args()

    gold = load_goldenset()
    with psycopg.connect(DSN) as conn:
        found = fetch_results(conn, gold.keys())

    items = []
    for h, res in found.items():
        items.append({
            "reference": gold[h]["reference"],
            "hypothesis": res["hypothesis"],
            "entities": res["entities"],
        })
    if len(items) < 10:
        print(f"매칭된 시스템 결과가 {len(items)}건뿐 — 채점 불가 (골든셋 배치를 먼저 돌릴 것)")
        sys.exit(2)

    hyps = [it["hypothesis"] for it in items]
    refs = [it["reference"] for it in items]
    chrf = sacrebleu.corpus_chrf(hyps, [refs]).score
    name_recall, n_confirmed = confirmed_name_recall(items)
    models = sorted({found[h]["model"] for h in found})

    print(f"n={len(items)} (링크 확정 인명 {n_confirmed}건) 모델={models}")
    print(f"chrF                = {chrf:.2f}")
    print(f"확정 인명 재현율    = {name_recall:.4f}")

    current = {"date": str(date.today()), "n": len(items), "models": models,
               "chrf": round(chrf, 2), "confirmed_name_recall": round(name_recall, 4)}

    if args.save_baseline or not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"기준선 저장: {BASELINE_PATH.name} {current}")
        return

    base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    chrf_drop = base["chrf"] - chrf
    recall_drop = base["confirmed_name_recall"] - name_recall
    print(f"기준선({base['date']}, n={base['n']}) 대비: chrF {-chrf_drop:+.2f}, 인명 재현율 {-recall_drop:+.4f}")

    violations = []
    if chrf_drop > CHRF_TOLERANCE:
        violations.append(f"chrF 하락 {chrf_drop:.2f} > 허용 {CHRF_TOLERANCE}")
    if recall_drop > NAME_RECALL_TOLERANCE:
        violations.append(f"인명 재현율 하락 {recall_drop:.4f} > 허용 {NAME_RECALL_TOLERANCE}")
    if violations:
        print("비열등 위반: " + "; ".join(violations))
        sys.exit(1)
    print("비열등 판정: 통과")


if __name__ == "__main__":
    main()
