"""
few-shot + 인물명 프롬프트 주입 번역
- fewshot_config.json 기본 프롬프트에
- ner_groundtruth_300.json 인물 정보를 [등장 인물] 블록으로 삽입
python run_few_nerinject.py
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

BASE = Path(__file__).parent

import os
from dotenv import load_dotenv
load_dotenv(BASE / ".env")
API_KEYS = [k.strip() for k in os.environ.get("GEMMA_API_KEY", "").split(",") if k.strip()]
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 5
OUTPUT_FILE    = BASE / "results300_few_nerinject.jsonl"
EVAL_FILE      = BASE / "eval300_1925.json"
CONFIG_FILE    = BASE / "fewshot_config.json"
NER_FILE       = BASE / "ner_groundtruth_300.json"

clients = [
    AsyncOpenAI(
        api_key=key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout=60.0,
    )
    for key in API_KEYS
]


def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text).strip()
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def build_prompt(template, examples, text, entities):
    base = template.format(
        examples="\n".join(f"- {e}" for e in examples),
        text=text,
    )
    if not entities:
        return base

    ner_block = "[등장 인물 — 반드시 아래 한글명 그대로 사용]\n"
    ner_block += "\n".join(f"  · {hanja} → {korean}" for _, hanja, korean in entities)

    # 원문 바로 앞에 인물 블록 삽입
    return base.replace(
        "위 문체로 다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:",
        ner_block + "\n위 문체로 다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:"
    )


async def translate_one(semaphore, prompt_text, entry, key_idx):
    async with semaphore:
        for attempt in range(4):
            client = clients[(key_idx + attempt) % len(clients)]
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt_text}],
                    max_tokens=2048,
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
    return {"id": entry["id"], "error": "max retries"}


async def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    from tqdm.asyncio import tqdm_asyncio

    data    = json.load(open(EVAL_FILE,  encoding="utf-8"))
    corpus  = {e["id"]: e for e in data["corpus"]}
    config  = json.load(open(CONFIG_FILE, encoding="utf-8"))
    gt      = json.load(open(NER_FILE,   encoding="utf-8"))
    template = config["prompt_template"]
    examples = config["fewshot_examples"]

    done = set()
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if "hypothesis" in r:
                        done.add(r["id"])
                except Exception:
                    pass

    remaining = [corpus[eid] for eid in data["ids"] if eid not in done]
    has_ner   = sum(1 for e in remaining if gt.get(e["id"]))
    print(f"미완료: {len(remaining)}개  (인물 주입 대상: {has_ner}개)")
    if not remaining:
        print("모두 완료!")
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    out_f  = open(OUTPUT_FILE, "a", encoding="utf-8")
    errors = 0

    async def process(entry, key_idx):
        nonlocal errors
        entities    = gt.get(entry["id"], [])
        prompt_text = build_prompt(template, examples, entry["original"], entities)
        result      = await translate_one(semaphore, prompt_text, entry, key_idx)
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()
        if "error" in result:
            errors += 1
        return result

    start = time.time()
    await tqdm_asyncio.gather(
        *[process(e, i % len(clients)) for i, e in enumerate(remaining)],
        desc="few+nerinject"
    )
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")


if __name__ == "__main__":
    asyncio.run(main())
