"""
few-shot 어투 가이드 실험:
- eval_set_1925.json 기반
- U0(영조) 번역 예시 5개를 프롬프트에 삽입
- 기존 gemma 결과와 BLEU 비교
"""
import asyncio
import json
import re
import time
from pathlib import Path
from openai import AsyncOpenAI
from sacrebleu.metrics import BLEU, CHRF
from tqdm.asyncio import tqdm_asyncio

API_KEY  = "YOUR_GOOGLE_AI_KEY"
MODEL    = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 10
OUTPUT_FILE = "eval_assets/results_fewshot_gemma.jsonl"
EVAL_FILE   = "eval_assets/eval_set_1925.json"
CONFIG_FILE = "eval_assets/fewshot_config.json"

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

def strip_thinking(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text)
    return text.strip()

def build_prompt(template, examples, text):
    examples_str = "\n".join(f"- {e}" for e in examples)
    return template.format(examples=examples_str, text=text)

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
                    "hypothesis": strip_thinking(resp.choices[0].message.content),
                    "input_tokens":  resp.usage.prompt_tokens if resp.usage else 0,
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

async def main():
    eval_data = json.load(open(EVAL_FILE, encoding="utf-8"))
    corpus    = eval_data["corpus"]
    config    = json.load(open(CONFIG_FILE, encoding="utf-8"))
    template  = config["prompt_template"]
    examples  = config["fewshot_examples"]

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

    remaining = [e for e in corpus if e["id"] not in done]
    print(f"eval set: {len(corpus)}개 | 완료: {len(done)} | 남은것: {len(remaining)}")

    if remaining:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        out_f = open(OUTPUT_FILE, "a", encoding="utf-8")
        errors = 0

        async def process(entry):
            nonlocal errors
            prompt_text = build_prompt(template, examples, entry["original"])
            result = await translate_one(semaphore, prompt_text, entry)
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()
            if "error" in result: errors += 1
            return result

        start = time.time()
        await tqdm_asyncio.gather(*[process(e) for e in remaining], desc="번역 중")
        out_f.close()
        print(f"소요: {(time.time()-start)/60:.1f}분  에러: {errors}")

    # 스코어링
    hyps, refs = [], []
    with open(OUTPUT_FILE, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "hypothesis" in r and "reference" in r:
                hyps.append(strip_thinking(r["hypothesis"]))
                refs.append(r["reference"])

    from kiwipiepy import Kiwi
    from tqdm import tqdm
    kiwi = Kiwi()

    bleu_c = BLEU(tokenize="char", effective_order=True).corpus_score(hyps, [refs]).score
    chrf_c = CHRF().corpus_score(hyps, [refs]).score

    print("형태소 분석 중...")
    hyps_m = [" ".join(t.form for t in kiwi.tokenize(h)) for h in tqdm(hyps, desc="hyp", leave=False)]
    refs_m  = [" ".join(t.form for t in kiwi.tokenize(r)) for r in tqdm(refs,  desc="ref", leave=False)]
    bleu_m = BLEU(tokenize="none", effective_order=True).corpus_score(hyps_m, [refs_m]).score
    chrf_m = CHRF().corpus_score(hyps_m, [refs_m]).score

    # 기존 베이스라인 (eval_set_1925, no few-shot)
    BASE = {"bleu_c": 34.98, "bleu_m": None, "chrf_c": None, "chrf_m": None}

    print(f"\n{'='*55}")
    print(f"{'':20} {'few-shot':>12} {'baseline':>12}")
    print(f"{'─'*55}")
    print(f"{'BLEU (char)':20} {bleu_c:>12.2f} {BASE['bleu_c']:>12.2f}")
    print(f"{'chrF++ (char)':20} {chrf_c:>12.2f}")
    print(f"{'BLEU (morph)':20} {bleu_m:>12.2f}")
    print(f"{'chrF++ (morph)':20} {chrf_m:>12.2f}")
    print(f"{'n':20} {len(hyps):>12}")
    print(f"{'='*55}")

    with open("eval_assets/result_fewshot_vs_baseline.txt", "w", encoding="utf-8") as f:
        f.write(f"모델: {MODEL}\n")
        f.write(f"프롬프트: few-shot (U0 영조 번역 예시 5개)\n")
        f.write(f"eval set: {len(hyps)}개 (eval_set_1925.json)\n\n")
        f.write(f"{'':20} {'few-shot':>12} {'baseline':>12}\n")
        f.write(f"{'BLEU (char)':20} {bleu_c:>12.2f} {BASE['bleu_c']:>12.2f}\n")
        f.write(f"{'chrF++ (char)':20} {chrf_c:>12.2f}\n")
        f.write(f"{'BLEU (morph)':20} {bleu_m:>12.2f}\n")
        f.write(f"{'chrF++ (morph)':20} {chrf_m:>12.2f}\n")

if __name__ == "__main__":
    asyncio.run(main())
