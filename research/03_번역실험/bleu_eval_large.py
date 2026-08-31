import asyncio
import json
import random
import re
import time
from pathlib import Path
from openai import AsyncOpenAI
from sacrebleu.metrics import BLEU, CHRF
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm

OR_TOKEN = "YOUR_OPENROUTER_KEY"
INPUT_FILE = "Merged_Corpus_Final.json"
SAMPLE_SIZE = 3000
RANDOM_SEED = 42
MAX_CONCURRENT = 50
N_BOOTSTRAP = 1000

MODELS = {
    "qwen3-235b": {
        "model_id": "qwen/qwen3-235b-a22b",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": OR_TOKEN,
        "output_file": "bleu_results_qwen3_235b.jsonl",
    },
    "deepseek-v3": {
        "model_id": "deepseek/deepseek-chat-v3-0324",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": OR_TOKEN,
        "output_file": "bleu_results_deepseek_v3.jsonl",
    },
}

PROMPT = "다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:\n\n{text}"


def strip_thinking(text):
    # Qwen3 <think>...</think>, Gemma <thought>...</thought>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()


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
                    "hypothesis": strip_thinking(resp.choices[0].message.content),
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

    done = {}
    if Path(output_file).exists():
        with open(output_file, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if "hypothesis" in r:
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
        elapsed = time.time() - start
        valid = len(done) + len(remaining) - errors
        print(f"[{name}] 완료 ({elapsed/60:.1f}분, 에러: {errors}, 유효: {valid})")

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

    cost = total_in * 0.13 / 1e6 + total_out * 0.60 / 1e6
    print(f"[{name}] BLEU={bleu_score:.2f}, chrF++={chrf_score:.2f}, 비용=${cost:.4f}")

    return {
        "model": name,
        "n": len(hypotheses),
        "bleu": bleu_score,
        "chrf": chrf_score,
        "cost": cost,
    }


async def main():
    data = json.load(open(INPUT_FILE, encoding="utf-8"))
    corpus = data["corpus"]

    random.seed(RANDOM_SEED)
    sample = random.sample(corpus, SAMPLE_SIZE)

    print(f"모델 {len(MODELS)}개 병렬 실행 | 샘플: {SAMPLE_SIZE}개\n")

    tasks = [run_model(name, config, sample) for name, config in MODELS.items()]
    results = await asyncio.gather(*tasks)

    print(f"\n{'='*65}")
    print(f"{'모델':<18} {'BLEU':>8} {'chrF++':>8} {'비용':>8}")
    print(f"{'─'*65}")
    for r in results:
        print(f"{r['model']:<18} {r['bleu']:>8.2f} {r['chrf']:>8.2f} ${r['cost']:>6.4f}")
    print(f"{'='*65}")
    print("* gemma-4-26b 결과는 bleu_score_gemma4_26b.txt 참조")


if __name__ == "__main__":
    asyncio.run(main())
