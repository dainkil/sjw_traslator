import json, time, datetime
from pathlib import Path

BASE = Path("ablation5way")
EVAL_IDS = set(json.load(open(BASE / "eval300_1925.json", encoding="utf-8"))["ids"])

def count_eval(path):
    done = 0
    p = Path(path)
    if not p.exists():
        return 0
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            r = json.loads(l)
            if r.get("id") in EVAL_IDS and "hypothesis" in r:
                done += 1
        except:
            pass
    return done

def count_file(path):
    done, err = 0, 0
    p = Path(path)
    if not p.exists():
        return 0, 0
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if '"hypothesis"' in l:
            done += 1
        elif '"error"' in l:
            err += 1
    return done, err

while True:
    now = datetime.datetime.now().strftime("%H:%M:%S")
    fs = count_eval(BASE / "results_fewshot.jsonl")
    v4, v4e = count_file(BASE / "results300_v4.jsonl")
    print(f"[{now}]  few-shot: {fs:3d}/300  |  v4: {v4:3d}/300 (err:{v4e})", flush=True)
    time.sleep(15)
