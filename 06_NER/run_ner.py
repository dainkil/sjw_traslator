import json, re, time, sys
import ahocorasick
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

BASE_AB  = r"c:\Users\kevin\OneDrive\Desktop\ner\sillok_crawler\ablation5way"
BASE_MM  = r"c:\Users\kevin\OneDrive\Desktop\ner\sillok_crawler\말모이"
OUT_PATH = r"c:\Users\kevin\OneDrive\Desktop\ner\ner_gold.json"

def L(path):
    return json.load(open(path, encoding="utf-8"))

# 0) 적재
try:
    pm = L(f"{BASE_AB}/person_master.json")
except json.JSONDecodeError as e:
    print(f"person_master.json 오류: {e}")
    pm = []

pm_by_id = {r.get("인물아이디", ""): r for r in pm}

inv = {}
try:
    for era, base in (("injo", BASE_AB), ("jeongjo", BASE_MM)):
        for surf, ids in L(f"{base}/inverted_index_{era}.json").items():
            inv.setdefault(surf, set()).update(ids)
    inv = {k: list(v) for k, v in inv.items()}
except Exception as e:
    print(f"역색인 로드 오류: {e}")

try:
    ev  = L(f"{BASE_AB}/eval300_1925.json")
    sjw = L(f"{BASE_AB}/sjw_raw_300.json")
except Exception as e:
    print(f"평가/실록 파일 로드 오류: {e}")
    ev = {"corpus": []}
    sjw = {}

# 1) 후보 추출
SURFACES = sorted(inv.keys(), key=len, reverse=True)
MAX_CAND = 10

A = ahocorasick.Automaton()
for idx, s in enumerate(SURFACES):
    A.add_word(s, s)
if SURFACES:
    A.make_automaton()

def meta(pid):
    r = pm_by_id.get(pid, {})
    return {"id": pid, "한글_명": r.get("한글_명"),
            "한자_명": (r.get("한자_명") or "").lstrip("﻿"),
            "본관": r.get("본관_표준"),
            "활동": f'{r.get("활동_시작")}~{r.get("활동_종료")}',
            "주요_관직": (r.get("관직_리스트") or [])[:4]}

def find_candidates(text):
    used = [False] * len(text)
    cands = []
    cid = 0
    found = []
    if SURFACES:
        for end_idx, s in A.iter(text):
            start_idx = end_idx - len(s) + 1
            found.append((start_idx, end_idx + 1, s))
    found.sort(key=lambda x: (-len(x[2]), x[0]))
    for start_idx, end_idx, s in found:
        if not any(used[start_idx:end_idx]):
            cands.append({"cand_id": cid, "surface": s,
                          "char_start": start_idx, "char_end": end_idx,
                          "kb_candidates": [meta(x) for x in inv[s][:MAX_CAND]]})
            for j in range(start_idx, end_idx): used[j] = True
            cid += 1
    return sorted(cands, key=lambda c: c["char_start"])

# 2) 프롬프트
PROMPT = r"""[역할]
너는 승정원일기·조선왕조실록 류 역사 텍스트에서 오직 "인명(PERSON)"만 판정하는 전문 주석자다.
주어진 한 문장에 대해, 사전(KB)이 미리 찾아 준 "후보 구간"들이 실제로 특정 실존 인물을
가리키는지(=개체명) 아닌지(=개체명 아님)를 판정하고, 사전이 놓친 인명만 추가한다.
인명 외의 어떤 유형(관직·관청·지명 등)도 절대 개체명으로 라벨하지 않는다.

[개체 정의 — 인명(PERSON)만]
· 개체명(O): 특정 실존 인물 한 명을 직접 지칭하는 표기.
  - 성명(姜銑/강선), 이름, 字·號·시호(諡號)로 특정인을 가리키는 경우
  - "도승지 홍국영"처럼 직함+성명이면 성명(홍국영) 부분만 개체명. 직함(도승지)은 제외.
· 개체명 아님(X) — 다음은 무조건 is_person=false:
  - 관직·관품·직함 자체(承旨, 通禮, 判書, 領議政 등)
  - 관청·기구명(院=사간원, 政院, 備局 등)
  - 지명·궁궐·전각명, 연호·간지, 묘호(廟號)·왕의 호칭
  - 일반어·행위어(察推 등), 우연히 사전 키와 겹친 한 글자(단어의 일부 등)
  - 직함만 있고 누구인지 특정되지 않는 경우

[입력]
· DOC_ID: {{DOC_ID}}
· SCRIPT_TYPE: {{SCRIPT_TYPE}}   (순한자 / 순한글 / 혼합)
· ERA: {{ERA}}                   (인물 활동연대 대조용)
· SENTENCE: {{SENTENCE}}
· CANDIDATES (사전이 찾은 후보 구간; kb_candidates = 그 표면형에 매칭된 인물 후보):
{{CANDIDATES}}

[판단 지침]
1. 문맥 우선. 사전 매칭은 단서일 뿐, 문맥상 특정 인물 지칭이 아니면 is_person=false.
2. 경계: 겹치는 후보는 가장 긴 인물 표기를 택한다(姜銑 vs 銑 → 姜銑). 긴 성명이 잡히면 그 안의 단자 후보는 false.
3. 동명이인 해소: kb_candidates 중 활동연대(활동_시작~종료)·본관·관직이 문맥과 맞는 인물을 resolved_kb_id로.
   한 명으로 못 좁히면 is_person=true로 두되 resolved_kb_id=null, confidence=low.
4. resolved_kb_id는 반드시 해당 후보의 kb_candidates 안의 id 중에서만 선택. 새 id를 지어내지 말 것.
   인물은 맞지만 KB에 없으면(예: 字·號로만 등장) resolved_kb_id=null.
5. 표기 유형 주의: 순한글은 동음이의가 많으니 신중히(낮은 confidence 허용), 순한자는 관직/기관 한자가
   인명 한자와 겹치는 오탐에 주의.
6. 누락 인명: CANDIDATES에 없지만 명백한 "인물" 표기만 missed_entities에 기재. 인명이 아니면 넣지 말 것.
7. 추측 금지. 불확실하면 단정 대신 confidence로 표현.

[출력 — 아래 JSON 하나만, 다른 텍스트·코드펜스 없이]
{
  "doc_id": "{{DOC_ID}}",
  "verifications": [
    {"cand_id": <int>, "surface": "<표면형>", "is_person": <true|false>,
     "resolved_kb_id": <"M_xxxxxxx" 또는 null>, "confidence": "<high|medium|low>",
     "reason": "<한국어 한 문장 근거>"}
  ],
  "missed_entities": [
    {"surface": "<표면형>", "resolved_kb_id": <"M_xxxxxxx" 또는 null>,
     "confidence": "<high|medium|low>", "reason": "<근거>"}
  ]
}"""

def build_prompt(doc_id, st, era, sent, cands):
    p = PROMPT
    for k, v in {"{{DOC_ID}}": doc_id, "{{SCRIPT_TYPE}}": st, "{{ERA}}": era,
                 "{{SENTENCE}}": sent,
                 "{{CANDIDATES}}": json.dumps(cands, ensure_ascii=False, indent=2)}.items():
        p = p.replace(k, v)
    return p

# 3) LLM 호출
from google import genai
from google.genai import types
client = genai.Client(api_key="YOUR_GOOGLE_AI_KEY")

def call_llm(prompt):
    for attempt in range(5):
        try:
            r = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=2000,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)
                )
            )
            return r.text
        except Exception as e:
            msg = str(e)
            if "503" in msg or "429" in msg:
                wait = 10 * (attempt + 1)
                print(f"  재시도 {attempt+1}/5 ({wait}s 대기)...", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("최대 재시도 초과")

def parse(txt):
    t = re.sub(r"^```(json)?|```$", "", txt.strip(), flags=re.MULTILINE).strip()
    # { ... } 범위만 추출
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1:
        t = t[start:end+1]
    return json.loads(t)

# 4) 태스크 구성
tasks = []
for c in ev.get("corpus", []):
    tasks.append((c["id"]+"|hanja",  "순한자", c["original"]))
    tasks.append((c["id"]+"|hangul", "순한글", c["reference"]))
for k, v in sjw.items():
    tasks.append((k+"|mixed", "혼합", v))

ERA = "injo"

# 5) 실행
gold = []
total = len(tasks)
print(f"총 {total}건 처리 시작")

if pm:
    for i, (doc_id, st, sent) in enumerate(tasks):
        cands = find_candidates(sent)
        if not cands:
            gold.append({"doc_id": doc_id, "script": st, "sentence": sent,
                         "verifications": [], "missed_entities": []})
            if (i+1) % 50 == 0:
                print(f"  {i+1}/{total} 완료 (후보 없음 스킵)")
            continue
        try:
            out = parse(call_llm(build_prompt(doc_id, st, ERA, sent, cands)))
            cmap = {c["cand_id"]: c for c in cands}
            for v in out.get("verifications", []):
                if v["cand_id"] in cmap:
                    v["char_start"] = cmap[v["cand_id"]]["char_start"]
                    v["char_end"]   = cmap[v["cand_id"]]["char_end"]
            out.update(script=st, sentence=sent)
            gold.append(out)
            if (i+1) % 50 == 0:
                print(f"  {i+1}/{total} 완료", flush=True)
                json.dump(gold, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            time.sleep(0.3)
        except Exception as e:
            print(f"에러 ({doc_id}): {e}")

    json.dump(gold, open(OUT_PATH, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n완료! 정답지 건수: {len(gold)}")
    print(f"저장 위치: {OUT_PATH}")
else:
    print("데이터 로드 실패로 중단")
