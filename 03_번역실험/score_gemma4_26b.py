import json
import re
import random
import time
from multiprocessing import Pool
from sacrebleu.metrics import BLEU, CHRF
from tqdm import tqdm
from kiwipiepy import Kiwi

INPUT_FILE = "bleu_results_gemma4_26b.jsonl"
OUTPUT_FILE = "bleu_score_gemma4_26b.txt"
N_BOOTSTRAP = 1000
RANDOM_SEED = 42

kiwi = Kiwi()


def strip_thinking(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()


def morpheme_tokenize(text):
    return " ".join(t.form for t in kiwi.tokenize(text))


def bootstrap_one(args):
    seed, hyps, refs = args
    random.seed(seed)
    n = len(hyps)
    idx = [random.randint(0, n - 1) for _ in range(n)]
    h = [hyps[i] for i in idx]
    r = [refs[i] for i in idx]
    bleu_c = BLEU(tokenize="char", effective_order=True).corpus_score(h, [r]).score
    chrf_c = CHRF().corpus_score(h, [r]).score
    bleu_m = BLEU(tokenize="none", effective_order=True).corpus_score(h, [r]).score
    chrf_m = CHRF().corpus_score(h, [r]).score
    return bleu_c, chrf_c, bleu_m, chrf_m


if __name__ == "__main__":
    hypotheses_raw, references = [], []
    with open(INPUT_FILE, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "hypothesis" in r and "reference" in r:
                hypotheses_raw.append(strip_thinking(r["hypothesis"]))
                references.append(r["reference"])

    n = len(hypotheses_raw)
    print(f"유효 샘플: {n}개")

    # ── 1차 결과: char-level (빠름) ──────────────────────────
    t0 = time.time()
    bleu_char = BLEU(tokenize="char", effective_order=True)
    chrf_metric = CHRF()
    bleu_c_score = bleu_char.corpus_score(hypotheses_raw, [references]).score
    chrf_c_score = chrf_metric.corpus_score(hypotheses_raw, [references]).score
    print(f"\n[1차 결과 - char-level]")
    print(f"  BLEU (char):   {bleu_c_score:.2f}")
    print(f"  chrF++ (char): {chrf_c_score:.2f}")
    print(f"  소요: {time.time()-t0:.1f}초\n")

    # ── 형태소 분석 ─────────────────────────────────────────
    print("형태소 분석 중...")
    t1 = time.time()
    hyps_morph = []
    for i, h in enumerate(tqdm(hypotheses_raw)):
        hyps_morph.append(morpheme_tokenize(h))
        if i == 0:
            elapsed = time.time() - t1
            eta = elapsed * n
            print(f"  ETA: 약 {eta/60:.1f}분 (샘플당 {elapsed:.2f}초 기준)")

    refs_morph = [morpheme_tokenize(r) for r in tqdm(references, desc="ref 형태소")]

    bleu_morph_metric = BLEU(tokenize="none", effective_order=True)
    bleu_m_score = bleu_morph_metric.corpus_score(hyps_morph, [refs_morph]).score
    chrf_m_score = CHRF().corpus_score(hyps_morph, [refs_morph]).score
    print(f"\n[2차 결과 - morpheme-level]")
    print(f"  BLEU (morpheme):   {bleu_m_score:.2f}")
    print(f"  chrF++ (morpheme): {chrf_m_score:.2f}")
    print(f"  형태소 소요: {(time.time()-t1)/60:.1f}분\n")

    # ── Bootstrap CI ─────────────────────────────────────────
    print(f"Bootstrap {N_BOOTSTRAP}회 (멀티프로세싱)...")
    random.seed(RANDOM_SEED)
    char_args = [(i, hypotheses_raw, references) for i in range(N_BOOTSTRAP)]
    morph_args = [(i, hyps_morph, refs_morph) for i in range(N_BOOTSTRAP)]

    t2 = time.time()
    with Pool() as pool:
        char_results = list(tqdm(pool.imap(bootstrap_one, char_args), total=N_BOOTSTRAP, desc="Bootstrap (char)"))
    print(f"  char bootstrap 완료: {(time.time()-t2)/60:.1f}분")

    bleu_c_boot = sorted(r[0] for r in char_results)
    chrf_c_boot = sorted(r[1] for r in char_results)

    t3 = time.time()
    with Pool() as pool:
        morph_results = list(tqdm(pool.imap(bootstrap_one, morph_args), total=N_BOOTSTRAP, desc="Bootstrap (morph)"))
    print(f"  morph bootstrap 완료: {(time.time()-t3)/60:.1f}분")

    bleu_m_boot = sorted(r[2] for r in morph_results)
    chrf_m_boot = sorted(r[3] for r in morph_results)

    lo, hi = 25, 975

    print(f"\n{'='*55}")
    print(f"모델: gemma-4-26b-a4b-it")
    print(f"평가 항목: {n:,}개")
    print(f"{'─'*55}")
    print(f"BLEU (char):      {bleu_c_score:.2f}  [95% CI: {bleu_c_boot[lo]:.2f} - {bleu_c_boot[hi]:.2f}]")
    print(f"chrF++ (char):    {chrf_c_score:.2f}  [95% CI: {chrf_c_boot[lo]:.2f} - {chrf_c_boot[hi]:.2f}]")
    print(f"BLEU (morpheme):  {bleu_m_score:.2f}  [95% CI: {bleu_m_boot[lo]:.2f} - {bleu_m_boot[hi]:.2f}]")
    print(f"chrF++ (morpheme):{chrf_m_score:.2f}  [95% CI: {chrf_m_boot[lo]:.2f} - {chrf_m_boot[hi]:.2f}]")
    print(f"{'='*55}")
    print(f"총 소요: {(time.time()-t0)/60:.1f}분")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"모델: gemma-4-26b-a4b-it\n")
        f.write(f"평가 항목: {n:,}개\n")
        f.write(f"BLEU (char): {bleu_c_score:.2f}  [95% CI: {bleu_c_boot[lo]:.2f} - {bleu_c_boot[hi]:.2f}]\n")
        f.write(f"chrF++ (char): {chrf_c_score:.2f}  [95% CI: {chrf_c_boot[lo]:.2f} - {chrf_c_boot[hi]:.2f}]\n")
        f.write(f"BLEU (morpheme): {bleu_m_score:.2f}  [95% CI: {bleu_m_boot[lo]:.2f} - {bleu_m_boot[hi]:.2f}]\n")
        f.write(f"chrF++ (morpheme): {chrf_m_score:.2f}  [95% CI: {chrf_m_boot[lo]:.2f} - {chrf_m_boot[hi]:.2f}]\n")

    print(f"\n결과 저장: {OUTPUT_FILE}")
