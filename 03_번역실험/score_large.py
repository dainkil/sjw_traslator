import json
import re
import sys
from sacrebleu.metrics import BLEU, CHRF
from tqdm import tqdm
from kiwipiepy import Kiwi

MODELS = {
    "deepseek-v3": "bleu_results_deepseek_v3.jsonl",
    "qwen3-235b": "bleu_results_qwen3_235b.jsonl",
}

kiwi = Kiwi()


def strip_thinking(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()


def morpheme_tokenize(text):
    return " ".join(t.form for t in kiwi.tokenize(text))


def score_model(name, filepath):
    hypotheses_raw, references = [], []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "hypothesis" in r and "reference" in r:
                hypotheses_raw.append(strip_thinking(r["hypothesis"]))
                references.append(r["reference"])

    n = len(hypotheses_raw)
    print(f"\n[{name}] 유효 샘플: {n}개")

    # char-level
    bleu_c = BLEU(tokenize="char", effective_order=True).corpus_score(hypotheses_raw, [references]).score
    chrf_c = CHRF().corpus_score(hypotheses_raw, [references]).score
    print(f"  BLEU (char):   {bleu_c:.2f}")
    print(f"  chrF++ (char): {chrf_c:.2f}")

    # morpheme-level
    print(f"  형태소 분석 중...")
    hyps_morph = [morpheme_tokenize(h) for h in tqdm(hypotheses_raw, desc="  hyp")]
    refs_morph = [morpheme_tokenize(r) for r in tqdm(references, desc="  ref")]

    bleu_m = BLEU(tokenize="none", effective_order=True).corpus_score(hyps_morph, [refs_morph]).score
    chrf_m = CHRF().corpus_score(hyps_morph, [refs_morph]).score
    print(f"  BLEU (morpheme):   {bleu_m:.2f}")
    print(f"  chrF++ (morpheme): {chrf_m:.2f}")

    out = f"bleu_score_{name}.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"모델: {name}\n")
        f.write(f"평가 항목: {n:,}개\n")
        f.write(f"BLEU (char): {bleu_c:.2f}\n")
        f.write(f"chrF++ (char): {chrf_c:.2f}\n")
        f.write(f"BLEU (morpheme): {bleu_m:.2f}\n")
        f.write(f"chrF++ (morpheme): {chrf_m:.2f}\n")
    print(f"  저장: {out}")

    return {"model": name, "n": n, "bleu_c": bleu_c, "chrf_c": chrf_c, "bleu_m": bleu_m, "chrf_m": chrf_m}


if __name__ == "__main__":
    results = []
    for name, filepath in MODELS.items():
        results.append(score_model(name, filepath))

    print(f"\n{'='*65}")
    print(f"{'모델':<18} {'BLEU(char)':>10} {'chrF(char)':>10} {'BLEU(morph)':>12} {'chrF(morph)':>12}")
    print(f"{'─'*65}")
    for r in results:
        print(f"{r['model']:<18} {r['bleu_c']:>10.2f} {r['chrf_c']:>10.2f} {r['bleu_m']:>12.2f} {r['chrf_m']:>12.2f}")

    # gemma 참고
    print(f"{'─'*65}")
    print(f"{'gemma-4-26b':<18} {'31.92':>10} {'27.59':>10} {'24.32':>12} {'28.99':>12}")
    print(f"{'='*65}")
