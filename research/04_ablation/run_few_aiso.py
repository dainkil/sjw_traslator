"""
few-shot + AISO per-query 번역
- 쿼리마다 패턴(REP/DEN/MEM/ROY/GEN)에 맞는 예시를 동적으로 선택
python run_few_aiso.py
"""
import asyncio, json, re, time
import numpy as np
from pathlib import Path
from itertools import combinations
from collections import Counter
from openai import AsyncOpenAI

BASE = Path(__file__).parent

import os
from dotenv import load_dotenv
load_dotenv(BASE / ".env")
API_KEYS = [k.strip() for k in os.environ.get("GEMMA_API_KEY", "").split(",") if k.strip()]
MODEL          = "gemma-4-26b-a4b-it"
MAX_CONCURRENT = 5
OUTPUT_FILE    = BASE / "results300_few_aiso.jsonl"
EVAL_FILE      = BASE / "eval300_1925.json"
CORPUS_FILE    = BASE / "Merged_Corpus_Final.json"
CONFIG_FILE    = BASE / "fewshot_config.json"

clients = [
    AsyncOpenAI(
        api_key=key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout=60.0,
    )
    for key in API_KEYS
]

# ── 피처 추출 ────────────────────────────────────────────────
_RE_HANJA = re.compile(r'[一-鿿]')

def extract_features(orig: str) -> np.ndarray:
    n = max(len(orig), 1)
    hanja = _RE_HANJA.findall(orig)
    n_hanja = max(len(hanja), 1)
    return np.array([
        min(n / 350.0, 1.0),
        float('啓曰' in orig or '又啓' in orig),
        float('不許' in orig or '不允' in orig),
        float('狀啓' in orig or '書啓' in orig),
        float('上曰' in orig or '傳曰' in orig or '上이' in orig),
        min(orig.count('·') / n * 5, 1.0),
        min((orig.count('月') + orig.count('日')) / n * 10, 1.0),
        len(set(hanja)) / n_hanja,
    ], dtype=float)

def get_pattern(feat: np.ndarray) -> str:
    if feat[1] > 0:   return "REP"
    elif feat[2] > 0: return "DEN"
    elif feat[3] > 0: return "MEM"
    elif feat[4] > 0: return "ROY"
    else:             return "GEN"

def get_length_bucket(orig: str) -> str:
    n = len(orig)
    if n < 50:    return "XS"
    elif n < 150: return "S"
    elif n < 350: return "M"
    else:         return "L"

# ── AISO ─────────────────────────────────────────────────────
def build_smart_m(X: np.ndarray, gamma: float = 0.5) -> np.ndarray:
    """
    Smart M (paper §2.3): M_ij = -|corr(i,j)| + γ(importance_j - importance_i)
    importance = 피처 엔트로피 (라벨 없으므로 MI 대신 entropy proxy 사용)
    """
    D = X.shape[1]
    # 피처 간 절대 상관 (repulsion term)
    corr = np.corrcoef(X.T)
    abs_corr = np.abs(corr)

    # 피처별 엔트로피 (importance proxy)
    importance = np.zeros(D)
    for d in range(D):
        col = X[:, d]
        # 연속형이면 10 bin 히스토그램으로 엔트로피 추정
        hist, _ = np.histogram(col, bins=10)
        hist = hist / (hist.sum() + 1e-8)
        importance[d] = -np.sum(hist * np.log(hist + 1e-8))

    imp_norm = (importance - importance.min()) / (importance.max() - importance.min() + 1e-8)

    M = np.zeros((D, D))
    for i in range(D):
        for j in range(D):
            if i != j:
                M[i, j] = -abs_corr[i, j] + gamma * (imp_norm[j] - imp_norm[i])
    return M


class AISOfewshot:
    def __init__(self, n_agents=20, n_iter=100, n_types=None,
                 alpha=0.25, beta=0.08, use_smart_m=True, seed=42):
        self.n_agents = n_agents; self.n_iter = n_iter
        self.n_types = n_types; self.alpha = alpha
        self.beta = beta; self.use_smart_m = use_smart_m
        self.seed = seed; self.visit_counts_ = None

    def _normalize(self, X):
        mn = X.min(axis=0); mx = X.max(axis=0)
        return (X - mn) / (mx - mn + 1e-8)

    def select(self, features: np.ndarray, n_select: int):
        rng = np.random.RandomState(self.seed)
        N_pool, D = features.shape
        K = self.n_types if self.n_types is not None else D
        X_norm = self._normalize(features)
        agent_pos = X_norm[rng.choice(N_pool, self.n_agents, replace=True)].copy()
        agent_W   = rng.dirichlet(np.ones(K), self.n_agents)
        if self.use_smart_m:
            M = build_smart_m(features)
            print("Smart M 사용 (corr-repulsion + entropy-gradient)")
        else:
            M = rng.uniform(-0.8, 2.0, (K, K))
        visit     = np.zeros(N_pool)
        for _ in range(self.n_iter):
            C = agent_W @ M @ agent_W.T
            np.fill_diagonal(C, 0)
            for i in range(self.n_agents):
                ci = C[i].copy()
                n_nb = min(3, self.n_agents - 1)
                attract_idx = np.argsort(ci)[-n_nb:]
                repel_idx   = np.argsort(ci)[:n_nb]
                force = np.zeros(D, dtype=float)
                for j in attract_idx: force += ci[j] * (agent_pos[j] - agent_pos[i])
                for j in repel_idx:   force += ci[j] * (agent_pos[j] - agent_pos[i])
                force /= (2 * n_nb)
                candidate = np.clip(agent_pos[i] + self.alpha * force, 0, 1)
                dists   = np.linalg.norm(X_norm - candidate, axis=1)
                nearest = int(np.argmin(dists))
                agent_pos[i] = X_norm[nearest]
                visit[nearest] += 1.0
                best_j = int(attract_idx[np.argmax(ci[attract_idx])])
                W_new  = (1 - self.beta) * agent_W[i] + self.beta * agent_W[best_j]
                agent_W[i] = W_new / W_new.sum()
        probs = visit + 1.0; probs /= probs.sum()
        selected = np.random.RandomState(self.seed).choice(N_pool, n_select, replace=False, p=probs)
        self.visit_counts_ = visit
        return selected, visit

# ── Per-query 선택 ────────────────────────────────────────────
def select_perquery(query_orig: str, top_entries, top_patterns, top_lengths,
                    n_select: int = 5, n_anchor: int = 1, rng_seed: int = 0) -> list:
    rng = np.random.RandomState(rng_seed)
    q_feat  = extract_features(query_orig)
    q_pat   = get_pattern(q_feat)
    q_lbuck = get_length_bucket(query_orig)
    length_order = {"XS": 0, "S": 1, "M": 2, "L": 3}
    q_lval  = length_order[q_lbuck]

    anchor_candidates = sorted(
        [(i, abs(length_order[top_lengths[i]] - q_lval))
         for i in range(len(top_entries)) if top_patterns[i] == q_pat],
        key=lambda x: x[1]
    )
    if not anchor_candidates:
        anchor_candidates = [(i, 0) for i in range(len(top_entries))]

    anchor_indices = [anchor_candidates[k][0] for k in range(min(n_anchor, len(anchor_candidates)))]
    used = set(anchor_indices)

    diverse_candidates = [i for i in range(len(top_entries)) if i not in used and top_patterns[i] != q_pat]
    pat_seen = set(top_patterns[i] for i in anchor_indices)
    diverse_selected = []
    for target_pat in ["GEN", "REP", "DEN", "MEM", "ROY"]:
        if target_pat in pat_seen: continue
        for i in diverse_candidates:
            if top_patterns[i] == target_pat and i not in used:
                diverse_selected.append(i); used.add(i); pat_seen.add(target_pat); break
        if len(diverse_selected) + len(anchor_indices) >= n_select: break

    remaining = [i for i in diverse_candidates if i not in used]
    rng.shuffle(remaining)
    while len(diverse_selected) + len(anchor_indices) < n_select and remaining:
        diverse_selected.append(remaining.pop(0))

    final = anchor_indices + diverse_selected[:n_select - len(anchor_indices)]
    return [top_entries[i] for i in final]

# ── 텍스트 정제 ───────────────────────────────────────────────
def strip(text):
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)
    text = re.sub(r"^○\s*", "", text.strip())
    text = re.sub(r"\s*○\s*", " ", text).strip()
    text = re.sub(r'\([^\)]*[一-鿿][^\)]*\)', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def build_prompt(template, examples, text):
    return template.format(examples="\n".join(f"- {e}" for e in examples), text=text)

# ── API 호출 ──────────────────────────────────────────────────
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

    # 데이터 로드
    data   = json.load(open(EVAL_FILE, encoding="utf-8"))
    corpus_map = {e["id"]: e for e in data["corpus"]}
    config = json.load(open(CONFIG_FILE, encoding="utf-8"))
    template = config["prompt_template"]

    # 62K 코퍼스 풀 구성 (eval300 제외)
    print("62K 코퍼스 로딩 중...")
    eval_ids = set(data["ids"])
    raw = json.load(open(CORPUS_FILE, encoding="utf-8"))
    pool = [
        e for e in raw["corpus"]
        if e["id"] not in eval_ids
        and e.get("translation", "").strip()
        and e.get("original", "").strip()
    ]
    print(f"풀: {len(pool):,}개")

    # AISO 피처 추출 + 실행
    print("피처 추출 중...")
    X_pool = np.array([extract_features(e["original"]) for e in pool])
    print("AISO 실행 중 (n_agents=25, n_iter=120, Smart M)...")
    aiso = AISOfewshot(n_agents=25, n_iter=120, alpha=0.25, beta=0.08, use_smart_m=True, seed=42)
    _, visit = aiso.select(X_pool, n_select=8)

    # 상위 500개 후보 풀
    TOP_CANDIDATES = 500
    top_idx      = np.argsort(visit)[::-1][:TOP_CANDIDATES]
    top_entries  = [pool[i] for i in top_idx]
    top_patterns = [get_pattern(X_pool[i]) for i in top_idx]
    top_lengths  = [get_length_bucket(pool[i]["original"]) for i in top_idx]
    print(f"상위 {TOP_CANDIDATES}개 패턴: {Counter(top_patterns)}")

    # 완료 항목 확인
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

    remaining = [corpus_map[eid] for eid in data["ids"] if eid not in done]
    print(f"미완료: {len(remaining)}개")
    if not remaining:
        print("모두 완료!")
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    out_f  = open(OUTPUT_FILE, "a", encoding="utf-8")
    errors = 0

    async def process(entry, key_idx):
        nonlocal errors
        selected = select_perquery(entry["original"], top_entries, top_patterns, top_lengths, n_select=5)
        examples = [e["translation"] for e in selected]
        prompt_text = build_prompt(template, examples, entry["original"])
        result = await translate_one(semaphore, prompt_text, entry, key_idx)
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()
        if "error" in result:
            errors += 1
        return result

    start = time.time()
    await tqdm_asyncio.gather(
        *[process(e, i % len(clients)) for i, e in enumerate(remaining)],
        desc="few+aiso"
    )
    out_f.close()
    print(f"\n완료: {len(remaining)-errors}개  에러: {errors}개  소요: {(time.time()-start)/60:.1f}분")


if __name__ == "__main__":
    asyncio.run(main())
