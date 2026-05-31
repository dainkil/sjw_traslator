import asyncio
import json
import random
import time
from pathlib import Path
from openai import AsyncOpenAI
from sacrebleu.metrics import BLEU, CHRF
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm

YOUR_HF_TOKEN = "YOUR_HF_TOKEN"
OR_TOKEN = "YOUR_OPENROUTER_KEY"
INPUT_FILE = "Merged_Corpus_Final.json"
SAMPLE_SIZE = 3000
RANDOM_SEED = 42
MAX_CONCURRENT = 20
N_BOOTSTRAP = 1000

MODELS = {
    "qwen3-4b": {
        "model_id": "Qwen/Qwen3-4B:featherless-ai",
        "base_url": "https://router.huggingface.co/v1",
        "api_key": YOUR_HF_TOKEN,
        "output_file": "bleu_results_qwen3_4b.jsonl",
    },
    "phi4-mini": {
        "model_id": "microsoft/Phi-4-mini-instruct:featherless-ai",
        "base_url": "https://router.huggingface.co/v1",
        "api_key": YOUR_HF_TOKEN,
        "output_file": "bleu_results_phi4_mini.jsonl",
    },
}

PROMPT = "다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:\n\n{text}"


async def translate_one(client, model_id, semaphore, entry):
    async with semaphore:
        for attempt in range(4):
            try:
                resp = await client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": PROMPT.format(text=entry["original"])}],
                    max_tokens=1024,
                    temperature=0.0,
                )
                return {
                    "id": entry["id"],
                    "reference": entry["translation"],
                    "hypothesis": resp.choices[0].message.content.strip(),
                    "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                    "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
                }
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                    await asyncio.sleep(2 ** (attempt + 2))
                elif attempt == 3:
                    return {"id": entry["id"], "error": err}
                else:
                    await asyncio.sleep(2 ** attempt)
        return {"id": entry["id"], "error": "max retries exceeded"}


def bootstrap_ci(hypotheses, references, n=N_BOOTSTRAP):
    bleu_m = BLEU(tokenize="char", effective_order=True)
    chrf_m = CHRF()
    size = len(hypotheses)
    bleu_scores, chrf_scores = [], []
    for _ in tqdm(range(n), desc="  Bootstrap", leave=False):
        idx = [random.randint(0, size - 1) for _ in range(size)]
        h = [hypotheses[i] for i in idx]
        r = [references[i] for i in idx]
        bleu_scores.append(bleu_m.corpus_score(h, [r]).score)
        chrf_scores.append(chrf_m.corpus_score(h, [r]).score)
    bleu_scores.sort()
    chrf_scores.sort()
    lo, hi = int(0.025 * n), int(0.975 * n)
    return (bleu_scores[lo], bleu_scores[hi]), (chrf_scores[lo], chrf_scores[hi])


async def run_model(name, config, sample):
    print(f"\n[{name}] 시작")
    output_file = config["output_file"]

    # resume
    done = {}
    if Path(output_file).exists():
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done[r["id"]] = r
                except Exception:
                    pass

    remaining = [e for e in sample if e["id"] not in done]
    print(f"[{name}] 완료: {len(done)} | 남은것: {len(remaining)}")

    if remaining:
        client = AsyncOpenAI(base_url=config["base_url"], api_key=config["api_key"])
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        out_f = open(output_file, "a", encoding="utf-8")
        errors = 0

        async def process(entry):
            nonlocal errors
            result = await translate_one(client, config["model_id"], semaphore, entry)
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()
            if "error" in result:
                errors += 1
            return result

        start = time.time()
        await tqdm_asyncio.gather(*[process(e) for e in remaining], desc=f"[{name}] 번역")
        out_f.close()
        print(f"[{name}] 완료 ({(time.time()-start)/60:.1f}분, 에러: {errors})")

    # 점수 계산
    hypotheses, references = [], []
    total_in, total_out = 0, 0
    with open(output_file, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "hypothesis" in r and "reference" in r:
                hypotheses.append(r["hypothesis"])
                references.append(r["reference"])
                total_in += r.get("input_tokens", 0)
                total_out += r.get("output_tokens", 0)

    bleu_m = BLEU(tokenize="char", effective_order=True)
    chrf_m = CHRF()
    bleu_score = bleu_m.corpus_score(hypotheses, [references]).score
    chrf_score = chrf_m.corpus_score(hypotheses, [references]).score

    print(f"[{name}] Bootstrap CI 계산 중...")
    (b_lo, b_hi), (c_lo, c_hi) = bootstrap_ci(hypotheses, references)

    # HF 가격 추정 ($0.10/1M in, $0.40/1M out 기준)
    cost = total_in * 0.10 / 1e6 + total_out * 0.40 / 1e6

    result = {
        "model": name,
        "n": len(hypotheses),
        "bleu": bleu_score,
        "bleu_ci": [b_lo, b_hi],
        "chrf": chrf_score,
        "chrf_ci": [c_lo, c_hi],
        "cost": cost,
    }

    with open(f"bleu_score_{name}.txt", "w", encoding="utf-8") as f:
        f.write(f"모델: {config['model_id']}\n")
        f.write(f"평가 항목: {len(hypotheses):,}개\n")
        f.write(f"BLEU (char): {bleu_score:.2f}  [95% CI: {b_lo:.2f}–{b_hi:.2f}]\n")
        f.write(f"chrF++: {chrf_score:.2f}  [95% CI: {c_lo:.2f}–{c_hi:.2f}]\n")
        f.write(f"실제 비용: ${cost:.4f}\n")

    return result


async def main():
    data = json.load(open(INPUT_FILE, encoding="utf-8"))
    corpus = data["corpus"]

    random.seed(RANDOM_SEED)
    sample = random.sample(corpus, SAMPLE_SIZE)

    print(f"모델 {len(MODELS)}개 병렬 실행 | 샘플: {SAMPLE_SIZE}개\n")

    # 3개 모델 동시 실행
    tasks = [run_model(name, config, sample) for name, config in MODELS.items()]
    results = await asyncio.gather(*tasks)

    # 최종 비교표
    print(f"\n{'='*60}")
    print(f"{'모델':<15} {'BLEU':>8} {'95% CI':>18} {'chrF++':>8} {'비용':>8}")
    print(f"{'─'*60}")
    for r in results:
        ci = f"[{r['bleu_ci'][0]:.1f}–{r['bleu_ci'][1]:.1f}]"
        print(f"{r['model']:<15} {r['bleu']:>8.2f} {ci:>18} {r['chrf']:>8.2f} ${r['cost']:>6.4f}")
    print(f"{'='*60}")
    print("* Gemma 4 E4B 결과는 bleu_score_gemma4_e4b.txt 참조")


if __name__ == "__main__":
    asyncio.run(main())
