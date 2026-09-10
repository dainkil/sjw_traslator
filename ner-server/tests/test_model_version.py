"""모델 버전이 가중치에서 파생되는지 검증 (M3-S2).

이 값이 M3 캐시 키에 들어가므로, 재학습본으로 갈아끼웠는데 값이 그대로면
번역 캐시가 옛 모델 결과를 계속 서빙한다 — 개선분이 캐시에 막혀 사라지는 실패다.
"""
from pathlib import Path

from app.ner import _model_version


def _model_dir(tmp_path: Path, weights: bytes, config: bytes = b'{"id2label": {}}') -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "model.onnx").write_bytes(weights)
    (tmp_path / "config.json").write_bytes(config)
    return tmp_path


def test_같은_모델은_같은_버전을_준다(tmp_path):
    d = _model_dir(tmp_path, b"weights-A")
    assert _model_version(d) == _model_version(d)
    assert _model_version(d).startswith("onnx-")


def test_가중치가_바뀌면_버전이_바뀐다(tmp_path):
    before = _model_version(_model_dir(tmp_path / "a", b"weights-A"))
    after = _model_version(_model_dir(tmp_path / "b", b"weights-B"))
    assert before != after


def test_라벨_설정이_바뀌어도_버전이_바뀐다(tmp_path):
    before = _model_version(_model_dir(tmp_path / "a", b"same", b'{"id2label": {"0": "O"}}'))
    after = _model_version(_model_dir(tmp_path / "b", b"same", b'{"id2label": {"0": "B-PER"}}'))
    assert before != after
