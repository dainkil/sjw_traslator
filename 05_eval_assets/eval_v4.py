"""
v4: 프롬프트 엔지니어링 극치
- 역할 지정 + 번역 원칙 + 과잉억제 규칙 + 8개 다양 예시 + 패턴 조건부 표현 주입
- output: ablation5way/results_v4.jsonl
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

API_KEY        = "YOUR_GOOGLE_AI_KEY"
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 3
OUTPUT_FILE    = "ablation5way/results_v4.jsonl"
EVAL_FILE      = "eval_assets/eval_set_1925.json"
EVAL200_FILE   = "ablation5way/eval200_ids.json"
MIN_LEN        = 100

client = AsyncOpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

# 8개 다양 예시 — 패턴별 1개씩, eval set 독립
EXAMPLES = [
    # 아뢰기를 (복잡한 보고)
    '홍문관이 아뢰기를, "정경세가 현재 상주에 있으니, 올라오도록 하유하소서." 하니, 윤허한다고 전교하였다.',
    # 전교하기를 (왕 명령)
    '전교하기를, "영의정 이원익에게 사관을 보내어 전유하라." 하였다.',
    # 윤허 (허락)
    '아뢰기를, "청컨대 전례대로 시행하게 하소서." 하니, 윤허한다고 전교하였다.',
    # 제수 (임명)
    '봉림대군에게 처음 직임을 제수하였다.',
    # 장계하기를 (지방 보고)
    '심양에서 재신이 장계하기를, "이달 9일에 왕세자가 서쪽으로 행차합니다." 하였다.',
    # 거둥하다 (행차)
    '상이 혼궁 소상제를 친히 지내기 위해 거둥하였다.',
    # 서계하기를 (서면 보고)
    '비변사가 서계하기를, "변경의 사정이 긴박하오니 속히 군병을 증파하소서." 하였다.',
    # 일반 서사 (패턴 없음)
    '이날 밤에 큰 바람이 불고 우레와 번개가 쳤다. 각 도의 감사에게 명하여 피해 상황을 보고하게 하였다.',
]

# 한자 패턴 → 사용해야 할 표현
POSITIVE_PATTERNS = [
    (r'傳敎曰|下敎曰|傳旨',          "전교하기를"),
    (r'啓曰|啓言|狀啓',              "아뢰기를 / 장계하기를"),
    (r'允許|允從|許之(?!諫)',        "윤허하다"),
    (r'不許|不允',                   "윤허하지 않다"),
    (r'拜.*爲|除授|落點',            "제수하다"),
    (r'行幸|臨幸',                   "거둥하다"),
    (r'還宮',                        "환궁하다"),
    (r'書啓',                        "서계하기를"),
    (r'馳啓',                        "치계하기를"),
]

# 실록에서 쓰면 안 되는 현대어 → 써야 할 실록 문체 (항상 적용)
MODERN_TO_SILLOK = [
    ("임명하다",          "제수하다"),
    ("허락하다",          "윤허하다"),
    ("허락하지 않다",     "윤허하지 않다"),
    ("행차하다",          "거둥하다"),
    ("돌아오다 / 귀환하다", "환궁하다"),
    ("보고하기를 (지방)", "장계하기를 / 서계하기를"),
    ("말씀하기를 / 명령하기를", "전교하기를 / 하교하기를"),
]


def detect_rules(original: str):
    """원문 패턴에서 반드시 써야 할 실록 표현 감지"""
    should_use = []
    for pat, phrase in POSITIVE_PATTERNS:
        if re.search(pat, original):
            should_use.append(phrase)
    return should_use


def build_prompt(original: str) -> str:
    examples_text = "\n".join(f"- {e}" for e in EXAMPLES)
    should_use = detect_rules(original)

    modern_block = "\n[현대어 X → 실록 문체 O — 반드시 대체]\n"
    modern_block += "\n".join(f"  · {modern} X → {sillok} O"
                              for modern, sillok in MODERN_TO_SILLOK)

    positive_block = ""
    if should_use:
        positive_block = "\n[이 원문 패턴에서 반드시 사용할 표현]\n"
        positive_block += "\n".join(f"  · {p}" for p in should_use)

    return f"""당신은 승정원일기 전문 번역가입니다. 원문 한문을 정확하고 자연스러운 현대 한국어로 번역합니다.

[번역 원칙]
1. 종결어미: -하였다, -하였나이다 사용 (-했다 절대 금지)
2. 왕 지칭: 상(上) 또는 전하 (왕·임금 금지)
3. 신하 자칭: 신(臣) 또는 소신 (저·나 금지)
4. 인용 형식: ~하기를, "..." 하였다
5. 관직·인명은 원문 음독 그대로
{modern_block}
[번역 예시]
{examples_text}
{positive_block}
위 원칙과 예시의 문체로 다음 한문을 번역하세요. 번역문만 출력하세요:

{original}"""


def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text).strip()
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)
    return re.sub(r'\s+', ' ', text).strip()


async def translate_one(semaphore, entry):
    async with semaphore:
        prompt_text = build_prompt(entry["original"])
        for attempt in range(4):
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

    corpus = {e["id"]: e for e in json.load(open(EVAL_FILE, encoding="utf-8"))["corpus"]}
    long_ids = json.load(open(EVAL200_FILE, encoding="utf-8"))
    print(f"eval200 대상: {len(long_ids)}개")

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
    print(f"완료: {len(done)} | 남은것: {len(remaining)}개")

    if not remaining:
        print("모두 완료!")
        return

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
    await tqdm_asyncio.gather(*[process(e) for e in remaining], desc="v4 번역")
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")


if __name__ == "__main__":
    asyncio.run(main())
