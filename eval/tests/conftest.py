"""eval/ 스크립트는 패키지가 아니라 CLI 묶음이다 — 테스트가 import할 수 있게 경로만 얹는다."""
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EVAL_DIR))
