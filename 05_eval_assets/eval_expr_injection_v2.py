"""
실험 #3-v2: 어투 주입 개선판
- 카테고리 수준이 아닌 한자 패턴 → 한국어 필수 표현 1:1 직접 매핑
- "참고하여" → "반드시 사용하세요" 강제
- 가장 강한 패턴 1개만 주입 (다중 주입 제거)
- eval set: 100자 이상 629개
- 출력: ablation5way/results_expr_inject_v2.jsonl
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

API_KEY        = "YOUR_GOOGLE_AI_KEY"
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 10
OUTPUT_FILE    = "ablation5way/results_expr_inject_v2.jsonl"
EVAL_FILE      = "eval_assets/eval_set_1925.json"
MIN_LEN        = 100

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# 한자 패턴 → 필수 사용 한국어 표현 (우선순위 순)
PATTERN_PHRASES = [
    (r'傳敎曰|傳敎하여曰|下敎曰',        "전교하기를"),
    (r'傳旨',                             "전지하기를"),
    (r'御命',                             "어명으로"),
    (r'允許|允從|許之(?!諫)',             "윤허하다"),
    (r'不許|不允',                        "윤허하지 않다"),
    (r'薨逝|薨',                          "훙서하다"),
    (r'卒逝|卒(?!業|業)',                 "졸하다"),
    (r'行幸|臨幸',                        "거둥하다"),
    (r'還宮',                             "환궁하다"),
    (r'拜.*爲|除授|落點',                 "제수하다"),
    (r'狀啓',                             "장계하기를"),
    (r'馳啓',                             "치계하기를"),
    (r'書啓',                             "서계하기를"),
    (r'啓曰|言啓|啓稟',                   "아뢰기를"),
]

def detect_phrase(original: str):
    """가장 먼저 매칭된 패턴의 필수 표현 반환. 없으면 None."""
    for pat, phrase in PATTERN_PHRASES:
        if re.search(pat, original):
            return phrase
    return None

def build_prompt(original: str, phrase) -> str:
    if phrase:
        guide = f'[번역 규칙] 다음 표현을 반드시 사용하세요: 「{phrase}」\n\n'
    else:
        guide = ""
    return (
        f"{guide}"
        f"다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:\n\n{original}"
    )

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

async def translate_one(semaphore, entry):
    phrase = detect_phrase(entry["original"])
    prompt = build_prompt(entry["original"], phrase)
    async with semaphore:
        for attempt in range(4):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1024,
                    temperature=0.0,
                )
                return {
                    "id": entry["id"],
                    "reference": entry["reference"],
                    "hypothesis": strip(resp.choices[0].message.content),
                    "phrase": phrase,
                }
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    await asyncio.sleep(2 ** (attempt + 2))
                elif attempt == 3:
                    return {"id": entry["id"], "error": err, "phrase": phrase}
                else:
                    await asyncio.sleep(2 ** attempt)
    return {"id": entry["id"], "error": "max retries exceeded"}

async def main():
    corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}
    long_ids = [eid for eid, e in corpus.items() if len(e["original"]) >= MIN_LEN]

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
    print(f"100자 이상: {len(long_ids)}개 | 완료: {len(done)} | 남은것: {len(remaining)}개")

    if not remaining:
        print("모두 완료됨!")
        return

    # 패턴 통계
    phrases = [detect_phrase(corpus[eid]["original"]) for eid in long_ids]
    from collections import Counter
    pc = Counter(p for p in phrases if p)
    print(f"필수표현 감지: {sum(1 for p in phrases if p)}/{len(long_ids)}개")
    for phrase, cnt in pc.most_common(10):
        print(f"  「{phrase}」: {cnt}")

    from tqdm.asyncio import tqdm_asyncio
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
    await tqdm_asyncio.gather(*[process(e) for e in remaining], desc="어투v2 번역")
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")

if __name__ == "__main__":
    asyncio.run(main())
