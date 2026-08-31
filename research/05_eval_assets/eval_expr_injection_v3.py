"""
실험 #3-v3: few-shot + 어투 주입 결합
- few-shot 5예시 (fewshot_config.json 동일)
- 아뢰기를 제외한 패턴에만 expr 주입 (SJW 용례 포함)
- 부정 예시 추가 ("임명하다 X")
- API: few-shot 키 통합 사용
- 출력: ablation5way/results_expr_inject_v3.jsonl
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

API_KEY        = "YOUR_GOOGLE_AI_KEY"
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 10
OUTPUT_FILE    = "ablation5way/results_expr_inject_v3.jsonl"
EVAL_FILE      = "eval_assets/eval_set_1925.json"
CONFIG_FILE    = "eval_assets/fewshot_config.json"
SJW_INDEX_FILE = "ablation5way/sjw_expr_index.json"
MIN_LEN        = 100

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# 한자 패턴 → (필수표현, 부정예시, SJW키)
# 아뢰기를 제외 — few-shot 예시가 이미 그 어투 보여줌
PATTERN_PHRASES = [
    (r'傳敎曰|下敎曰|하교하기를',           "전교하기를",      "말씀하기를 X",      "전교하기를"),
    (r'傳旨',                               "전지하기를",      "명령하기를 X",      "전교하기를"),
    (r'允許|允從|許之(?!諫)',               "윤허하다",        "허락하다 X",        "윤허하다"),
    (r'不許|不允',                          "윤허하지 않다",   "허락하지 않다 X",   "윤허하지 않다"),
    (r'拜.*爲|除授|落點',                   "제수하다",        "임명하다 X",        "제수하다"),
    (r'狀啓',                               "장계하기를",      "보고하기를 X",      "장계하기를"),
    (r'馳啓',                               "치계하기를",      "급보하기를 X",      "치계하기를"),
    (r'書啓',                               "서계하기를",      "서면보고하기를 X",  "서계하기를"),
    (r'行幸|臨幸',                          "거둥하다",        "행차하다 X",        "거둥하다"),
    (r'還宮',                               "환궁하다",        "돌아오다 X",        "환궁하다"),
]

def detect_pattern(original: str):
    for pat, phrase, neg, sjw_key in PATTERN_PHRASES:
        if re.search(pat, original):
            return phrase, neg, sjw_key
    return None, None, None

def build_prompt(fewshot_examples, original, phrase, neg, sjw_example):
    examples_text = "\n".join(f"- {e}" for e in fewshot_examples)

    if phrase:
        sjw_note = f'\n  · 용례: "{sjw_example}"' if sjw_example else ""
        rule = (
            f"\n[번역 규칙]\n"
            f"  · 「{phrase}」를 반드시 사용하세요. ({neg}){sjw_note}\n"
        )
    else:
        rule = ""

    return (
        f"다음은 조선시대 한문 번역 예시입니다. 이 어투와 문체를 참고하여 번역하세요.\n\n"
        f"[번역 예시]\n{examples_text}"
        f"{rule}\n"
        f"위 문체로 다음 한문을 현대 한국어로 번역하세요. 번역문만 출력하세요:\n\n{original}"
    )

def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    return re.sub(r"\s*○\s*", " ", text).strip()

async def translate_one(semaphore, entry, prompt_text, phrase):
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
    # SJW 코퍼스에서 직접 추출한 다양한 패턴 예시 (eval set 독립, 한자 제거)
    fewshot_examples = [
        '전교하기를, "영의정 이원익에게 사관을 보내어 전유하라."하였다.',
        '홍문관이 아뢰기를, "정경세가 현재 상주에 있으니, 올라오도록 하유하소서."하니, 윤허한다고 전교하였다.',
        '봉림대군에게 처음 직임을 제수하였다.',
        '심양에서 재신이 장계하기를, "이달 9일에 왕세자가 서쪽으로 행차합니다."하였다.',
        '상이 혼궁 소상제를 친히 지내기 위해 거둥하였다.',
    ]
    sjw_index = json.load(open(SJW_INDEX_FILE, encoding="utf-8")) if Path(SJW_INDEX_FILE).exists() else {}

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
    from collections import Counter
    pc = Counter()
    for eid in long_ids:
        phrase, _, _ = detect_pattern(corpus[eid]["original"])
        pc[phrase or "(없음)"] += 1
    print(f"\n패턴 분포 (아뢰기를 제외):")
    for k, v in pc.most_common():
        print(f"  {k}: {v}개")

    from tqdm.asyncio import tqdm_asyncio
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    out_f = open(OUTPUT_FILE, "a", encoding="utf-8")
    errors = 0

    async def process(entry):
        nonlocal errors
        phrase, neg, sjw_key = detect_pattern(entry["original"])
        sjw_example = None
        if sjw_key and sjw_key in sjw_index and sjw_index[sjw_key]["examples"]:
            sjw_example = re.sub(r'\([^)]+\)', '', sjw_index[sjw_key]["examples"][0]).strip()

        prompt_text = build_prompt(fewshot_examples, entry["original"], phrase, neg, sjw_example)
        result = await translate_one(semaphore, entry, prompt_text, phrase)
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()
        if "error" in result:
            errors += 1
        return result

    start = time.time()
    await tqdm_asyncio.gather(*[process(e) for e in remaining], desc="v3 번역")
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")

if __name__ == "__main__":
    asyncio.run(main())
