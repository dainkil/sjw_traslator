import time
import subprocess

dv_f = r"c:\Users\kevin\OneDrive\Desktop\sillok_crawler\bleu_results_deepseek_v3.jsonl"
qw_f = r"c:\Users\kevin\OneDrive\Desktop\sillok_crawler\bleu_results_qwen3_235b.jsonl"

def count(f):
    try:
        with open(f, encoding="utf-8") as fh:
            return sum(1 for line in fh if '"hypothesis"' in line)
    except:
        return 0

prev_dv, prev_qw, prev_t = 0, 0, time.time()
while True:
    time.sleep(10)
    now = time.time()
    dv, qw = count(dv_f), count(qw_f)
    dt = now - prev_t
    if prev_dv > 0 and dt > 0:
        dv_rate = (dv - prev_dv) / dt
        qw_rate = (qw - prev_qw) / dt
        dv_eta = int((3000 - dv) / dv_rate / 60) if dv_rate > 0 else 999
        qw_eta = int((3000 - qw) / qw_rate / 60) if qw_rate > 0 else 999
        print(f"DeepSeek: {dv}/3000 (ETA ~{dv_eta}분) | Qwen3-235B: {qw}/3000 (ETA ~{qw_eta}분)", flush=True)
    else:
        print(f"DeepSeek: {dv}/3000 | Qwen3-235B: {qw}/3000 | 초기화중...", flush=True)
    prev_dv, prev_qw, prev_t = dv, qw, now
