"""
few-shot: 100자 이상 629개 중 미완료 386개만 추가 번역
기존 results_fewshot_gemma.jsonl에 append
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

API_KEY        = "YOUR_GOOGLE_AI_KEY"
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 3
OUTPUT_FILE    = "ablation5way/results_fewshot.jsonl"
EVAL_FILE      = "eval_assets/eval_set_1925.json"
CONFIG_FILE    = "eval_assets/fewshot_config.json"
MIN_LEN        = 100

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

def build_prompt(template, examples, text):
    return template.format(examples="\n".join(f"- {e}" for e in examples), text=text)

async def translate_one(semaphore, prompt_text, entry):
    async with semaphore:
        for attempt in range(4):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt_text}],
                    max_tokens=1024,
                    temperature=0.0,
                )
                return {
                    "id": entry["id"],
                    "reference": entry["reference"],
                    "hypothesis": strip(resp.choices[0].message.content),
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

async def main():
    corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}
    config   = json.load(open(CONFIG_FILE, encoding="utf-8"))
    template = config["prompt_template"]
    examples = config["fewshot_examples"]

    # 100자 이상 IDs
    long_ids = {eid for eid, e in corpus.items() if len(e["original"]) >= MIN_LEN}

    # 기존 완료 IDs
    done = set()
    if Path(OUTPUT_FILE).exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if "hypothesis" in r:
                        done.add(r["id"])
                except Exception:
                    pass

    remaining = [corpus[eid] for eid in long_ids if eid not in done]
    print(f"100자 이상: {len(long_ids)}개 | 완료: {len(long_ids & done)} | 남은것: {len(remaining)}개")

    if not remaining:
        print("모두 완료됨!")
        return

    from tqdm.asyncio import tqdm_asyncio
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    out_f = open(OUTPUT_FILE, "a", encoding="utf-8")
    errors = 0

    async def process(entry):
        nonlocal errors
        result = await translate_one(semaphore, build_prompt(template, examples, entry["original"]), entry)
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()
        if "error" in result:
            errors += 1
        return result

    start = time.time()
    await tqdm_asyncio.gather(*[process(e) for e in remaining], desc="번역 중")
    out_f.close()
    print(f"\n완료: {len(remaining) - errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")

if __name__ == "__main__":
    asyncio.run(main())
