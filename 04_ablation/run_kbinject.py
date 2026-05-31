"""
kb-inject 번역 실행 (ablation5way/ 폴더에서 실행)
python run_kbinject.py

파이프라인:
  1. SillokBERT-NER  → 원문 한자 개체명 추출
  2. person_master   → 한자명 → 한글명 매핑
  3. id_lookup_injo  → 인물 ID 조회 (인조 시기)
  4. inverted_index  → RAG 관련 문서 스니펫
  5. SillokBERT(base)→ MLM 문맥 키워드
  6. 전부 프롬프트 주입 → Gemma 4 번역
"""
import asyncio, json, re, time
from pathlib import Path
from openai import AsyncOpenAI

BASE = Path(__file__).parent

API_KEYS = [
    "YOUR_GOOGLE_AI_KEY",
    "YOUR_GOOGLE_AI_KEY",
    "YOUR_GOOGLE_AI_KEY",
]
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 5
OUTPUT_FILE    = BASE / "results300_kbinject.jsonl"
EVAL_FILE      = BASE / "eval300_1925.json"

POSITIVE_PATTERNS = [
    (r'傳敎曰|下敎曰|傳旨',       "전교하기를"),
    (r'啓曰|啓言|狀啓',           "아뢰기를 / 장계하기를"),
    (r'允許|允從|許之(?!諫)',     "윤허하다"),
    (r'不許|不允',                "윤허하지 않다"),
    (r'拜.*爲|除授|落點',         "제수하다"),
    (r'行幸|臨幸',                "거둥하다"),
    (r'還宮',                     "환궁하다"),
    (r'書啓',                     "서계하기를"),
    (r'馳啓',                     "치계하기를"),
]
MODERN_TO_SILLOK = [
    ("임명하다",               "제수하다"),
    ("허락하다",               "윤허하다"),
    ("허락하지 않다",          "윤허하지 않다"),
    ("행차하다",               "거둥하다"),
    ("돌아오다 / 귀환하다",    "환궁하다"),
    ("보고하기를 (지방)",      "장계하기를 / 서계하기를"),
    ("말씀하기를 / 명령하기를","전교하기를 / 하교하기를"),
]
EXAMPLES = [
    '홍문관이 아뢰기를, "정경세가 현재 상주에 있으니, 올라오도록 하유하소서." 하니, 윤허한다고 전교하였다.',
    '전교하기를, "영의정 이원익에게 사관을 보내어 전유하라." 하였다.',
    '봉림대군에게 처음 직임을 제수하였다.',
    '심양에서 재신이 장계하기를, "이달 9일에 왕세자가 서쪽으로 행차합니다." 하였다.',
    '상이 혼궁 소상제를 친히 지내기 위해 거둥하였다.',
    '비변사가 서계하기를, "변경의 사정이 긴박하오니 속히 군병을 증파하소서." 하였다.',
    '이날 밤에 큰 바람이 불고 우레와 번개가 쳤다.',
]

clients = [
    AsyncOpenAI(
        api_key=k,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout=120.0,
    )
    for k in API_KEYS
]


def load_kbs():
    person_raw = json.load(open(BASE / "person_master.json", encoding="utf-8"))
    person_map = {}
    for e in person_raw:
        h = e.get("hanja") or e.get("name_hanja", "")
        k = e.get("korean") or e.get("name_korean", "")
        if h and k:
            person_map[h] = {"korean": k, "id": str(e.get("id", ""))}
    id_lookup = json.load(open(BASE / "id_lookup_injo.json",       encoding="utf-8"))
    inv_index = json.load(open(BASE / "inverted_index_injo.json",  encoding="utf-8"))
    print(f"KB: 인물 {len(person_map)}개 | id_lookup {len(id_lookup)}개 | inv_index {len(inv_index)}개")
    return person_map, id_lookup, inv_index


def load_models():
    from transformers import pipeline, AutoTokenizer, AutoModelForMaskedLM
    ner = pipeline("ner", model="ddokbaro/SillokBert-NER", aggregation_strategy="simple")
    tok = AutoTokenizer.from_pretrained("ddokbaro/SillokBert")
    mdl = AutoModelForMaskedLM.from_pretrained("ddokbaro/SillokBert")
    mdl.eval()
    return ner, tok, mdl


def extract_entities(ner, text):
    try:
        return [r["word"].replace(" ", "") for r in ner(text) if r["score"] > 0.5]
    except Exception:
        return []


def get_context_tokens(tok, mdl, text, top_k=5):
    import torch
    try:
        inputs = tok(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            logits = mdl(**inputs).logits[0].mean(dim=0)
        ids = logits.topk(top_k * 3).indices.tolist()
        tokens = tok.convert_ids_to_tokens(ids)
        return [t for t in tokens if not t.startswith("##") and len(t) > 1][:top_k]
    except Exception:
        return []


def resolve_entity(word, person_map, id_lookup, inv_index):
    korean, pid, refs = None, None, []
    if word in person_map:
        korean = person_map[word]["korean"]
        pid    = person_map[word]["id"]
    if not pid and word in id_lookup:
        pid = str(id_lookup[word])
    if pid and pid in inv_index:
        for doc in inv_index[pid][:2]:
            refs.append((doc.get("text", doc) if isinstance(doc, dict) else str(doc))[:60])
    return korean, refs


def build_prompt(original, entity_data, context_tokens):
    should_use   = [ph for pat, ph in POSITIVE_PATTERNS if re.search(pat, original)]
    modern_block = "\n[현대어 X → 실록 문체 O]\n" + "\n".join(f"  · {m} X → {s} O" for m, s in MODERN_TO_SILLOK)
    pos_block    = ("\n[반드시 사용할 표현]\n" + "\n".join(f"  · {p}" for p in should_use)) if should_use else ""
    kb_block     = ""
    named = [(w, k, r) for w, k, r in entity_data if k]
    if named:
        kb_block = "\n[등장 인물 한자→한글]\n"
        for w, k, refs in named:
            line = f"  · {w} → {k}"
            if refs:
                line += f"  (참고: {refs[0]}…)"
            kb_block += line + "\n"
    return f"""당신은 승정원일기 전문 번역가입니다. 원문 한문을 정확하고 자연스러운 현대 한국어로 번역합니다.

[번역 원칙]
1. 종결어미: -하였다 사용 (-했다 금지)
2. 왕 지칭: 상(上) 또는 전하
3. 신하 자칭: 신(臣) 또는 소신
4. 인용 형식: ~하기를, "..." 하였다
5. 관직·인명은 원문 음독
{modern_block}
[번역 예시]
{chr(10).join(f"- {e}" for e in EXAMPLES)}
{pos_block}{kb_block}
위 원칙과 예시의 문체로 다음 한문을 번역하세요. 번역문만 출력하세요:

{original}"""


def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text).strip()
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)
    return re.sub(r'\s+', ' ', text).strip()


async def translate_one(semaphore, entry, key_idx, entity_data, context_tokens):
    async with semaphore:
        prompt = build_prompt(entry["original"], entity_data, context_tokens)
        for attempt in range(4):
            client = clients[(key_idx + attempt) % len(clients)]
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=2048,
                    temperature=0.0,
                )
                return {
                    "id": entry["id"],
                    "reference": entry["reference"],
                    "hypothesis": strip(resp.choices[0].message.content),
                    "injected": [f"{w}→{k}" for w, k, _ in entity_data if k],
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

    print("모델 로딩 중...")
    ner, tok, bert = load_models()
    person_map, id_lookup, inv_index = load_kbs()

    data   = json.load(open(EVAL_FILE, encoding="utf-8"))
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
    print(f"kb-inject 미완료: {len(remaining)}개")
    if not remaining:
        print("모두 완료!")
        return

    print("NER + KB 사전 계산 중...")
    precomputed = {}
    for entry in remaining:
        eid, orig = entry["id"], entry["original"]
        words       = extract_entities(ner, orig)
        entity_data = [(w, *resolve_entity(w, person_map, id_lookup, inv_index)) for w in words]
        ctx         = get_context_tokens(tok, bert, orig)
        precomputed[eid] = (entity_data, ctx)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    out_f     = open(OUTPUT_FILE, "a", encoding="utf-8")
    errors    = 0

    async def process(entry, key_idx):
        nonlocal errors
        entity_data, ctx = precomputed[entry["id"]]
        result = await translate_one(semaphore, entry, key_idx, entity_data, ctx)
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()
        if "error" in result:
            errors += 1
        return result

    start = time.time()
    await tqdm_asyncio.gather(
        *[process(e, i % len(clients)) for i, e in enumerate(remaining)],
        desc="kb-inject"
    )
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")


if __name__ == "__main__":
    asyncio.run(main())
