"""
v4 번역 실행 (ablation5way/ 폴더에서 실행)
python run_v4.py
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

BASE = Path(__file__).parent

API_KEYS = [
    "YOUR_GOOGLE_AI_KEY",
]
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 10
OUTPUT_FILE    = BASE / "results300_v4.jsonl"
EVAL_FILE      = BASE / "eval300_1925.json"

clients = [
    AsyncOpenAI(
        api_key=key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout=120.0,
    )
    for key in API_KEYS
]

EXAMPLES = [
    '홍문관이 아뢰기를, "정경세가 현재 상주에 있으니, 올라오도록 하유하소서." 하니, 윤허한다고 전교하였다.',
    '전교하기를, "영의정 이원익에게 사관을 보내어 전유하라." 하였다.',
    '아뢰기를, "청컨대 전례대로 시행하게 하소서." 하니, 윤허한다고 전교하였다.',
    '봉림대군에게 처음 직임을 제수하였다.',
    '심양에서 재신이 장계하기를, "이달 9일에 왕세자가 서쪽으로 행차합니다." 하였다.',
    '상이 혼궁 소상제를 친히 지내기 위해 거둥하였다.',
    '비변사가 서계하기를, "변경의 사정이 긴박하오니 속히 군병을 증파하소서." 하였다.',
    '이날 밤에 큰 바람이 불고 우레와 번개가 쳤다. 각 도의 감사에게 명하여 피해 상황을 보고하게 하였다.',
]

POSITIVE_PATTERNS = [
    (r'傳敎曰|下敎曰|傳旨',         "전교하기를"),
    (r'啓曰|啓言|狀啓',             "아뢰기를 / 장계하기를"),
    (r'允許|允從|許之(?!諫)',       "윤허하다"),
    (r'不許|不允',                  "윤허하지 않다"),
    (r'拜.*爲|除授|落點',           "제수하다"),
    (r'行幸|臨幸',                  "거둥하다"),
    (r'還宮',                       "환궁하다"),
    (r'書啓',                       "서계하기를"),
    (r'馳啓',                       "치계하기를"),
]

MODERN_TO_SILLOK = [
    ("임명하다",                "제수하다"),
    ("허락하다",                "윤허하다"),
    ("허락하지 않다",           "윤허하지 않다"),
    ("행차하다",                "거둥하다"),
    ("돌아오다 / 귀환하다",     "환궁하다"),
    ("보고하기를 (지방)",       "장계하기를 / 서계하기를"),
    ("말씀하기를 / 명령하기를", "전교하기를 / 하교하기를"),
]


def detect_rules(original: str):
    return [phrase for pat, phrase in POSITIVE_PATTERNS if re.search(pat, original)]


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


def has_hanja(text):
    return bool(re.search(r'[一-鿿]', text))


RETRY_MSG = "\n\n번역문에 한자가 포함되어 있습니다. 한자를 하나도 쓰지 말고 모두 한국어 음독으로 바꿔 다시 번역하세요."


async def translate_one(semaphore, entry, key_idx):
    async with semaphore:
        prompt_text = build_prompt(entry["original"])
        for attempt in range(4):
            client = clients[(key_idx + attempt) % len(clients)]
            # 한자 재시도 시 프롬프트에 경고 추가
            cur_prompt = prompt_text if attempt == 0 else prompt_text + RETRY_MSG
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": cur_prompt}],
                    max_tokens=2048,
                    temperature=0.0,
                )
                hyp = strip(resp.choices[0].message.content)
                if has_hanja(hyp) and attempt < 3:
                    await asyncio.sleep(1)
                    continue
                return {
                    "id": entry["id"],
                    "reference": entry["reference"],
                    "hypothesis": hyp,
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

    data = json.load(open(EVAL_FILE, encoding="utf-8"))
    corpus = {e["id"]: e for e in data["corpus"]}

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
    print(f"v4 미완료: {len(remaining)}개 (완료: {len(done)})")
    if not remaining:
        print("모두 완료!")
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    out_f = open(OUTPUT_FILE, "a", encoding="utf-8")
    errors = 0

    async def process(entry, key_idx):
        nonlocal errors
        result = await translate_one(semaphore, entry, key_idx)
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()
        if "error" in result:
            errors += 1
        return result

    start = time.time()
    await tqdm_asyncio.gather(*[process(e, i % len(clients)) for i, e in enumerate(remaining)], desc="v4")
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")


if __name__ == "__main__":
    asyncio.run(main())
