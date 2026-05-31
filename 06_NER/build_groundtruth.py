import json, re, sys, time, urllib.request
from pathlib import Path
import hanja as hanja_lib
sys.stdout.reconfigure(encoding='utf-8')

BASE_AB  = Path(r"C:\Users\kevin\OneDrive\Desktop\ner\sillok_crawler\ablation5way")
OUT_GT   = BASE_AB / "ner_groundtruth_300.json"
PROXY    = "http://YOUR_PROXY_ADDRESS"

ev  = json.load(open(BASE_AB / "eval300_1925.json", encoding="utf-8"))
inv = json.load(open(BASE_AB / "inverted_index_injo.json", encoding="utf-8"))
pm  = json.load(open(BASE_AB / "person_master.json", encoding="utf-8"))
pm_by_id = {r.get("인물아이디", ""): r for r in pm}

def korean_name(hanja_str):
    pids = inv.get(hanja_str, [])
    if pids:
        name = pm_by_id.get(pids[0], {}).get("한글_명")
        if name:
            return name
    # KB에 없으면 hanja 라이브러리로 독음 변환
    reading = hanja_lib.translate(hanja_str, "substitution")
    return reading if reading and reading != hanja_str else None

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
)
opener.addheaders = [("User-Agent", "Mozilla/5.0")]

def fetch_persons(doc_id):
    url = f"https://sjw.history.go.kr/id/{doc_id}"
    for attempt in range(4):
        try:
            resp = opener.open(url, timeout=20)
            html = resp.read().decode("utf-8")
            spans = re.findall(
                r'<span[^>]*class="[^"]*idx_person[^"]*"[^>]*>([^<]+)</span>',
                html
            )
            return spans
        except Exception as e:
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                print(f"  실패 {doc_id}: {e}")
                return []

# 기존 결과 이어받기
groundtruth = {}
if OUT_GT.exists():
    groundtruth = json.load(open(OUT_GT, encoding="utf-8"))
    print(f"기존 로드: {len(groundtruth)}개")

ids = ev["ids"]
print(f"총 {len(ids)}개 처리")

for i, doc_id in enumerate(ids):
    if doc_id in groundtruth:
        continue

    spans = fetch_persons(doc_id)
    entities = []
    seen = set()
    for hanja in spans:
        hanja = hanja.strip()
        if not hanja or hanja in seen:
            continue
        seen.add(hanja)
        korean = korean_name(hanja)
        if korean:
            entities.append(["PER", hanja, korean])

    groundtruth[doc_id] = entities

    if (i + 1) % 10 == 0:
        print(f"  {i+1}/{len(ids)} | {doc_id} | 엔티티: {len(entities)}", flush=True)
        json.dump(groundtruth, open(OUT_GT, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    time.sleep(0.4)

json.dump(groundtruth, open(OUT_GT, "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

total  = sum(len(v) for v in groundtruth.values())
docs_w = sum(1 for v in groundtruth.values() if v)
print(f"\n완료: 문서 {len(groundtruth)}개 | 엔티티 있는 문서: {docs_w}개 | 총 엔티티: {total}개")
print(f"저장: {OUT_GT}")
