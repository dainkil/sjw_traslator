"""프롬프트 회귀 게이트 (ADR-013) — 결정론적 절반.

생산 템플릿+패턴 바이트의 체크섬(= PromptAssembler.version()과 같은 규칙)이 eval/baseline_scores.json의
prompt_versions에 있어야 통과한다. 프롬프트를 고치고 기준선을 재저장하지 않으면 CI가 빨개진다 —
"프롬프트를 바꾸면 기존 평가 세트에 미치는 영향을 검증한다"의 CI 쪽 절반이다. 확률적 절반(실제 품질)은
CI가 LLM을 호출하지 않으므로(ADR-016) 오프라인 배치 + 사전 고정 비열등 임계로 한다(score_db.py, prompt_ablation.py).

기준선이 아직 pre-V4(prompt_version 없는 2026-09-01 결과)면 skip한다. `score_db.py --prompt-version <v>
--save-baseline`으로 재저장하는 순간 이 게이트가 켜진다 — M3.5-S2 종료 단계가 그 스위치다.
"""
import json

import pytest

import prompt_ablation as pa
import score_db


def test_production_prompt_version_is_baselined():
    base = json.loads(score_db.BASELINE_PATH.read_text(encoding="utf-8"))
    versions = [v for v in base.get("prompt_versions", []) if v and not v.startswith("(pre-V4")]
    if not versions:
        pytest.skip("기준선이 prompt_version 없는(pre-V4) 결과로 저장돼 있다 — "
                    "score_db.py --prompt-version <v> --save-baseline 으로 재저장하면 이 게이트가 켜진다")
    current = pa.expected_version(pa.PROD_TEMPLATE)
    assert current in versions, (
        f"프롬프트 체크섬 {current}가 기준선 {versions}에 없다. 프롬프트(또는 positive-patterns.tsv)가 바뀌었다 — "
        f"골든셋 비열등을 다시 재고(score_db.py) 통과하면 --save-baseline, 아니면 되돌릴 것.")
