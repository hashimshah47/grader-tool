"""Settings, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
# Model used for rubric parsing and code generation, and a (cheaper) one for judging.
MODEL = os.environ.get("CHECKER_MODEL", "claude-sonnet-5-5")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", MODEL)
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
MAX_FIX_ATTEMPTS = int(os.environ.get("MAX_FIX_ATTEMPTS", "3"))
REVIEW_PASS = os.environ.get("REVIEW_PASS", "1") not in ("0", "false", "False")
GRADE_CONCURRENCY = int(os.environ.get("GRADE_CONCURRENCY", "4"))
CHECKER_TIMEOUT = float(os.environ.get("CHECKER_TIMEOUT", "90"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
# Force demo mode even if a key is present (handy for a public portfolio deployment).
DEMO_ONLY = os.environ.get("DEMO_ONLY", "0") in ("1", "true", "True")

EXAMPLES = ROOT / "examples"
GRADEKIT_API = ROOT / "gradekit" / "API.md"

DATA_DIR.mkdir(parents=True, exist_ok=True)
