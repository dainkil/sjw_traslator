"""
실험 #3: 어투 사전 주입 (Expression Dictionary Injection)
- 원문 한문 패턴 감지 → 관련 표현 카테고리만 동적 추출 → 프롬프트 주입
- eval set: 100자 이상 629개
- 출력: eval_assets/results_expr_injection.jsonl
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

API_KEY        = "YOUR_GOOGLE_AI_KEY"
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 10
OUTPUT_FILE    = "ablation5way/results_expr_inject.jsonl"
EVAL_FILE      = "eval_assets/eval_set_1925.json"
EXPR_FILE      = "eval_assets/expression_dict.json"
MIN_LEN        = 100

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# 한문 패턴 → 주입할 카테고리 매핑
PATTERN_TO_CATEGORY = {
    r'啓曰|言啓|啓稟|啓請|啓達|上啓|馳啓|狀啓': "보고/아룀",
    r'傳敎|下敎|命曰|御命|傳旨':                  "명령/하교",
    r'允許|允從|許之|不許|不允':                   "윤허/불허",
    r'拜|除授|差下|落點|授職':                      "임명/제수",
    r'卒|薨|卒逝|薨逝':                            "죽음",
    r'請|建請|啓請|陳請':                          "청원/요청",
    r'行幸|駕|還宮|出宮|臨幸':                     "행차/이동",
}

# 카테고리별 주입 문구
CATEGORY_GUIDE = {
    "보고/아룀":   "신하가 왕에게 보고·아룀: 아뢰기를 / 계하기를 / 품하기를 / 장계하기를",
    "명령/하교":   "왕이 명령·지시: 전교하기를 / 하교하기를 / 명하기를 / 이르기를",
    "윤허/불허":   "허락·불허: 윤허하다 / 허락하다 / 윤허하지 않다 / 불허하다",
    "임명/제수":   "관직 임명: 제수하다 / 차하다 / 삼다 / 낙점하다",
    "죽음":        "사망 표현: 졸하다 / 훙서하다 / 처형하다 / 주살하다",
    "청원/요청":   "요청·청원: 청하기를 / 계청하다 / 간청하다",
    "행차/이동":   "왕의 이동: 거둥하다 / 행행하다 / 환궁하다",
}

def detect_categories(original: str) -> list[str]:
    cats = []
    for pat, cat in PATTERN_TO_CATEGORY.items():
        if re.search(pat, original):
            cats.append(cat)
    return cats

def build_prompt(original: str, categories: list[str]) -> str:
    if categories:
        guide_lines = "\n".join(f"- {CATEGORY_GUIDE[c]}" for c in categories if c in CATEGORY_GUIDE)
        guide_block = f"[번역 어투 가이드]\n{guide_lines}\n\n"
    else:
        guide_block = ""
    return (
        f"{guide_block}"
        f"위 어투를 참고하여 다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:\n\n{original}"
    )

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

async def translate_one(semaphore, entry):
    cats = detect_categories(entry["original"])
    prompt = build_prompt(entry["original"], cats)
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
                    "categories": cats,
                }
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    await asyncio.sleep(2 ** (attempt + 2))
                elif attempt == 3:
                    return {"id": entry["id"], "error": err, "categories": cats}
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
    await tqdm_asyncio.gather(*[process(e) for e in remaining], desc="어투주입 번역")
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")

if __name__ == "__main__":
    asyncio.run(main())
