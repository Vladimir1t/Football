"""The whole pipeline: extract -> transform -> marts -> data quality.

Each step is a plain function, so wrapping them in an orchestrator (Airflow,
Prefect, Dagster) is a matter of one task per function — see docs/TASKS.md.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from . import dq, extract, metrics, transform
from .config import ROOT, Settings
from .db import Database

log = logging.getLogger(__name__)

SQL_DIR = ROOT / "sql"


def init_schema(db: Database) -> None:
    db.executescript((SQL_DIR / "schema.sql").read_text())
    db.conn.commit()


def build_marts(db: Database) -> int:
    db.executescript((SQL_DIR / "marts.sql").read_text())
    db.conn.commit()
    return metrics.build_player_load(db)


def run(settings: Settings, as_of: date) -> dq.RunSummary:
    db = Database(settings.db_url)
    try:
        init_schema(db)
        loaded = extract.run(db, settings.raw_dir)
        core = transform.run(db, settings.reference_dir)
        load_rows = build_marts(db)
        summary = dq.run_checks(db, as_of)
        report = dq.write_report(summary, settings.reports_dir, {**loaded, **core, "mart_player_load": load_rows})
        log.info("report written to %s", report)
        dq.send_alert(summary, settings.telegram_token, settings.telegram_chat_id)
        return summary
    finally:
        db.close()


def check_only(settings: Settings, as_of: date) -> dq.RunSummary:
    db = Database(settings.db_url)
    try:
        summary = dq.run_checks(db, as_of)
        dq.write_report(summary, settings.reports_dir)
        dq.send_alert(summary, settings.telegram_token, settings.telegram_chat_id)
        return summary
    finally:
        db.close()


def default_as_of(raw_dir: Path) -> date:
    """The generator records its 'today'; for real data use the actual date."""
    manifest = raw_dir / "_manifest.json"
    if manifest.exists():
        import json

        return date.fromisoformat(json.loads(manifest.read_text())["as_of"])
    return date.today()
