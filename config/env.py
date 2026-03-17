from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent


def load_project_env() -> None:
    """Load local overrides first, then shared defaults, without overriding real env vars."""
    load_dotenv(BASE_DIR / ".env.local", override=False)
    load_dotenv(BASE_DIR / ".env", override=False)
