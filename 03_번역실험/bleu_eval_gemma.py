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


def strip_thinking(text):
    return re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL).strip()

API_KEY = "YOUR_GOOGLE_AI_KEY"
MODEL = "gemma-4-26b-a4b-it"
INPUT_FILE = "Merged_Corpus_Final.json"
OUTPUT_FILE = "bleu_results_gemma4_e4b.jsonl"
SAMPLE_SIZE = 3000
RANDOM_SEED = 42
MAX_CONCURRENT = 15
N_BOOTSTRAP = 1000

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

PROMPT = "다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:\n\n{text}"


async def translate_one(semaphore, entry):
    async with semaphore:
        for attempt in range(4):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
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
                if "429" in err or "quota" in err.lower():
                    await asyncio.sleep(2 ** (attempt + 2))
                elif attempt == 3:
                    return {"id": entry["id"], "error": err}
                else:
                    await asyncio.sleep(2 ** attempt)
        return {"id": entry["id"], "error": "max retries exceeded"}


def bootstrap_ci(hypotheses, references, n=N_BOOTSTRAP, ci=0.95):
    bleu_metric = BLEU(tokenize="char", effective_order=True)
    chrf_metric = CHRF()
    size = len(hypotheses)
    bleu_scores, chrf_scores = [], []

    for _ in tqdm(range(n), desc="Bootstrap CI 계산 중"):
        idx = [random.randint(0, size - 1) for _ in range(size)]
        h = [hypotheses[i] for i in idx]
        r = [references[i] for i in idx]
        bleu_scores.append(bleu_metric.corpus_score(h, [r]).score)
        chrf_scores.append(chrf_metric.corpus_score(h, [r]).score)

    bleu_scores.sort()
    chrf_scores.sort()
    lo, hi = int((1 - ci) / 2 * n), int((1 + ci) / 2 * n)
    return (bleu_scores[lo], bleu_scores[hi]), (chrf_scores[lo], chrf_scores[hi])


async def main():
    data = json.load(open(INPUT_FILE, encoding="utf-8"))
    corpus = data["corpus"]

    # resume
    done = {}
    if Path(OUTPUT_FILE).exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if "hypothesis" in r:
                        done[r["id"]] = r
                except Exception:
                    pass

    random.seed(RANDOM_SEED)
    sample = random.sample(corpus, SAMPLE_SIZE)
    remaining = [e for e in sample if e["id"] not in done]

    print(f"모델: {MODEL}")
    print(f"샘플: {SAMPLE_SIZE}개 | 완료: {len(done)} | 남은것: {len(remaining)}\n")

    if remaining:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        out_f = open(OUTPUT_FILE, "a", encoding="utf-8")
        errors = 0

        async def process(entry):
            nonlocal errors
            result = await translate_one(semaphore, entry)
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()
            if "error" in result:
                errors += 1
            return result

        start = time.time()
        await tqdm_asyncio.gather(*[process(e) for e in remaining], desc="번역 중")
        out_f.close()
        print(f"\n소요 시간: {(time.time()-start)/60:.1f}분 | 에러: {errors}")

    # 결과 로드
    hypotheses, references = [], []
    total_in, total_out = 0, 0
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "hypothesis" in r and "reference" in r:
                hypotheses.append(strip_thinking(r["hypothesis"]))
                references.append(r["reference"])
                total_in += r.get("input_tokens", 0)
                total_out += r.get("output_tokens", 0)

    cost = total_in * 0.075 / 1e6 + total_out * 0.30 / 1e6

    # 점수 계산
    bleu_metric = BLEU(tokenize="char", effective_order=True)
    chrf_metric = CHRF()
    bleu_score = bleu_metric.corpus_score(hypotheses, [references]).score
    chrf_score = chrf_metric.corpus_score(hypotheses, [references]).score

    print(f"\n{N_BOOTSTRAP}회 Bootstrap resampling 시작...")
    (b_lo, b_hi), (c_lo, c_hi) = bootstrap_ci(hypotheses, references)

    print(f"\n{'='*50}")
    print(f"모델: {MODEL}")
    print(f"평가 항목: {len(hypotheses):,}개")
    print(f"{'─'*50}")
    print(f"BLEU (char):  {bleu_score:.2f}  [95% CI: {b_lo:.2f} – {b_hi:.2f}]")
    print(f"chrF++:       {chrf_score:.2f}  [95% CI: {c_lo:.2f} – {c_hi:.2f}]")
    print(f"{'─'*50}")
    print(f"실제 비용:    ${cost:.4f}")
    print(f"{'='*50}")

    with open("bleu_score_gemma4_e4b.txt", "w", encoding="utf-8") as f:
        f.write(f"모델: {MODEL}\n")
        f.write(f"평가 항목: {len(hypotheses):,}개\n")
        f.write(f"BLEU (char): {bleu_score:.2f}  [95% CI: {b_lo:.2f} – {b_hi:.2f}]\n")
        f.write(f"chrF++: {chrf_score:.2f}  [95% CI: {c_lo:.2f} – {c_hi:.2f}]\n")
        f.write(f"실제 비용: ${cost:.4f}\n")


if __name__ == "__main__":
    asyncio.run(main())
