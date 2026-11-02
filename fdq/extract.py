"""Extract: raw deliveries -> staging tables, as delivered (no fixes here).

Loading is idempotent per file: re-running deletes the rows previously loaded
from the same file and inserts them again, so a re-delivered or re-run file
never creates duplicates in staging. `_file` and `_loaded_at` keep lineage.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .db import Database

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reload(db: Database, table: str, df: pd.DataFrame, file: Path) -> int:
    df = df.copy()
    df["_file"] = file.name
    df["_loaded_at"] = _now()
    db.execute(f"DELETE FROM {table} WHERE _file = ?", [file.name])
    return db.insert_df(table, df)


def load_provider_a(db: Database, raw_dir: Path) -> dict[str, int]:
    counts = {"stg_a_matches": 0, "stg_a_lineups": 0, "stg_a_events": 0}
    for file in sorted((raw_dir / "provider_a").glob("*.json")):
        payload = json.loads(file.read_text())
        m = payload["match"]
        matches = pd.DataFrame([{
            "match_id": m["match_id"], "match_date": m["date"],
            "home_team": m["home_team"], "away_team": m["away_team"],
        }])
        lineups = pd.DataFrame(payload["lineups"]).rename(columns={"name": "player_name"})
        lineups.insert(0, "match_id", m["match_id"])
        events = pd.DataFrame(payload["events"]).rename(columns={"type": "event_type"})
        events.insert(1, "match_id", m["match_id"])
        # player_id is nullable: keep it as a nullable integer, not float.
        events["player_id"] = events["player_id"].astype("Int64")

        counts["stg_a_matches"] += _reload(db, "stg_a_matches", matches, file)
        counts["stg_a_lineups"] += _reload(db, "stg_a_lineups", lineups[[
            "match_id", "player_id", "player_name", "team", "jersey", "minutes"]], file)
        counts["stg_a_events"] += _reload(db, "stg_a_events", events[[
            "event_id", "match_id", "period", "minute", "second", "event_type",
            "team", "player_id", "outcome", "xg"]], file)
    return counts


def load_provider_b(db: Database, raw_dir: Path) -> dict[str, int]:
    counts = {"stg_b_matches": 0, "stg_b_player_stats": 0}
    for file in sorted((raw_dir / "provider_b").glob("matches_*.csv")):
        df = pd.read_csv(file, dtype={"match_id": str}).rename(columns={"date": "match_date"})
        counts["stg_b_matches"] += _reload(db, "stg_b_matches", df, file)
    for file in sorted((raw_dir / "provider_b").glob("players_*.csv")):
        df = pd.read_csv(file, dtype={"match_id": str, "player_key": str})
        counts["stg_b_player_stats"] += _reload(db, "stg_b_player_stats", df, file)
    return counts


def load_gps(db: Database, raw_dir: Path) -> dict[str, int]:
    total = 0
    for file in sorted((raw_dir / "gps").glob("gps_*.csv")):
        df = pd.read_csv(file)
        total += _reload(db, "stg_gps", df, file)
    return {"stg_gps": total}


def run(db: Database, raw_dir: Path) -> dict[str, int]:
    if not raw_dir.exists():
        raise FileNotFoundError(f"{raw_dir} does not exist: run `python -m fdq generate` first")
    counts: dict[str, int] = {}
    with db.transaction():
        counts.update(load_provider_a(db, raw_dir))
        counts.update(load_provider_b(db, raw_dir))
        counts.update(load_gps(db, raw_dir))
    for table, n in counts.items():
        log.info("extract: %s <- %d rows", table, n)
    return counts
