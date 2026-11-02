"""Settings come from environment variables, with defaults for a local run."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Our club. Everything club-specific (GPS, load metrics) is computed for this team.
OWN_TEAM_ID = 1


@dataclass(frozen=True)
class Settings:
    db_url: str
    raw_dir: Path
    reference_dir: Path
    reports_dir: Path
    telegram_token: str | None
    telegram_chat_id: str | None


def load_settings() -> Settings:
    return Settings(
        db_url=os.getenv("FDQ_DB_URL", f"sqlite:///{ROOT / 'data' / 'fdq.db'}"),
        raw_dir=Path(os.getenv("FDQ_RAW_DIR", ROOT / "data" / "raw")),
        reference_dir=Path(os.getenv("FDQ_REFERENCE_DIR", ROOT / "reference")),
        reports_dir=Path(os.getenv("FDQ_REPORTS_DIR", ROOT / "reports")),
        telegram_token=os.getenv("FDQ_TELEGRAM_TOKEN"),
        telegram_chat_id=os.getenv("FDQ_TELEGRAM_CHAT_ID"),
    )
