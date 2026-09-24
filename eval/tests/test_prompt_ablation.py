"""prompt_ablation.py 단위 테스트 — 체크섬 버전 파생·변형 목록·표본 재현성. LLM 0회, DB·api 불필요."""
import json
import re

import prompt_ablation as pa


def test_expected_version_is_content_derived(tmp_path):
    v0 = pa.expected_version(pa.PROD_TEMPLATE)
    assert re.fullmatch(r"main-[0-9a-f]{8}", v0)
    copy = tmp_path / "copy.st"
    copy.write_bytes(pa.PROD_TEMPLATE.read_bytes())
    assert pa.expected_version(copy) == v0                       # 같은 바이트 → 같은 버전 (위치 무관)
    copy.write_bytes(pa.PROD_TEMPLATE.read_bytes() + b"\n")
    assert pa.expected_version(copy) != v0                       # 1바이트 → 다른 버전


def test_variants_cover_every_prompt_file():
    vs = pa.variants()
    assert vs["v0"] == pa.PROD_TEMPLATE
    files = sorted(p.name for p in pa.PROMPTS_DIR.glob("v*.st"))
    assert files, "eval/prompts/에 변형이 없다"
    assert sorted(p.name for v, p in vs.items() if v != "v0") == files
    variant_versions = [pa.expected_version(p) for v, p in vs.items() if v != "v0"]
    assert len(set(variant_versions)) == len(variant_versions)            # 변형끼리 버전 충돌 없음
    # 생산 프롬프트는 모든 변형과 다르거나(실험 중), 정확히 한 변형과 같다(채택 후 — M3.5-S2에서 v4를 복사)
    assert variant_versions.count(pa.expected_version(pa.PROD_TEMPLATE)) <= 1


def test_stratified_sample_is_reproducible():
    """seed 42로 다시 뽑으면 커밋된 eval60_stratified.json과 id가 같아야 한다 — 표본이 재현되지 않으면 실험이 재현되지 않는다."""
    recorded = json.loads(pa.SAMPLE_PATH.read_text(encoding="utf-8"))
    picked = pa.pick_sample(recorded["n"], recorded["seed"])
    assert picked["ids"] == recorded["ids"]
    assert picked["groundtruth_names"] == recorded["groundtruth_names"]
