"""ONNX Runtime 기반 토큰 분류 추론 + BIO 스팬 집계 (공용 로직)."""
import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

MAX_LEN = 512


def _model_version(model_dir: Path) -> str:
    """가중치·라벨에서 파생한 모델 버전 (예: onnx-3f2a9c1e).

    M3 캐시 무효화가 이 값을 쓴다 — 재학습본으로 갈아끼우면 값이 반드시 바뀌므로
    "번역 캐시에 옛 모델 결과가 남아 개선분이 안 보이는" 실패가 생기지 않는다.
    설정 문자열이 아니라 파일 파생이라 버전 올리는 걸 깜빡할 수가 없다 (KB·프롬프트와 같은 방식).
    """
    h = hashlib.sha256()
    for name in ("model.onnx", "config.json"):
        with (model_dir / name).open("rb") as f:      # 가중치가 174MB라 스트리밍으로 읽는다
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return "onnx-" + h.hexdigest()[:8]


class NerModel:
    def __init__(self, model_dir: Path):
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        cfg = json.loads((model_dir / "config.json").read_text())
        self.id2label = {int(k): v for k, v in cfg["id2label"].items()}
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(model_dir / "model.onnx"), so, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.version = _model_version(model_dir)

    def predict(self, text: str, min_score: float = 0.5) -> list[dict]:
        enc = self.tokenizer(
            text, return_tensors="np", truncation=True, max_length=MAX_LEN,
            return_offsets_mapping=True,
        )
        offsets = enc.pop("offset_mapping")[0]
        feeds = {k: v for k, v in enc.items() if k in self.input_names}
        logits = self.session.run(None, feeds)[0][0]  # (seq, num_labels)
        # softmax
        e = np.exp(logits - logits.max(axis=-1, keepdims=True))
        probs = e / e.sum(axis=-1, keepdims=True)
        ids = probs.argmax(axis=-1)

        entities, cur = [], None
        for i, (label_id, (s, t)) in enumerate(zip(ids, offsets)):
            if s == t:  # 특수 토큰
                continue
            label = self.id2label[int(label_id)]
            score = float(probs[i, label_id])
            if label.startswith("B-") or (label.startswith("I-") and
                                          (cur is None or cur["type"] != label[2:])):
                if cur:
                    entities.append(cur)
                cur = {"type": label[2:], "start": int(s), "end": int(t), "scores": [score]}
            elif label.startswith("I-") and cur and cur["type"] == label[2:]:
                cur["end"] = int(t)
                cur["scores"].append(score)
            else:  # O
                if cur:
                    entities.append(cur)
                cur = None
        if cur:
            entities.append(cur)

        out = []
        for ent in entities:
            score = float(np.mean(ent["scores"]))
            if score < min_score:
                continue
            out.append({
                "surface": text[ent["start"]:ent["end"]].replace(" ", ""),
                "type": ent["type"], "start": ent["start"], "end": ent["end"],
                "score": round(score, 4),
            })
        return out
