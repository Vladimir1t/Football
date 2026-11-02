"""Transform: staging -> core model with canonical IDs.

    teams    : provider names -> canonical team (reference/teams.csv + fuzzy)
    players  : provider A is the master; B and GPS are matched onto it
    matches  : A match <-> B match by date + both teams
    events   : deduplicated on their natural key (retries arrive with new IDs)
    gps      : exact duplicates dropped, physically impossible rows flagged

Core tables are rebuilt in full on every run (fine at this scale, trivially
idempotent). Problems are *flagged*, not silently fixed: the DQ suite and the
report make them visible.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from .config import OWN_TEAM_ID
from .db import Database
from .matching import Candidate, match_player, match_team

log = logging.getLogger(__name__)

MAX_HUMAN_SPEED_KMH = 38.0       # elite sprinters peak ~44 km/h; footballers stay below ~37
DROPOUT_MIN_DURATION = 30.0      # minutes on the unit ...
DROPOUT_MAX_DISTANCE = 500.0     # ... but almost no distance: the unit died or was not worn

EVENT_NATURAL_KEY = ["match_id", "period", "minute", "second", "event_type", "team", "player_id"]


def load_reference_teams(reference_dir: Path) -> tuple[list[tuple[int, str, list[str]]], pd.DataFrame]:
    """The team reference (справочник) is maintained by hand: id, canonical name, known aliases."""
    df = pd.read_csv(reference_dir / "teams.csv")
    return [(int(r.team_id), r.name, str(r.aliases).split("|")) for r in df.itertuples()], df


def build_teams(db: Database, reference_dir: Path) -> dict[tuple[str, str], int | None]:
    teams, ref = load_reference_teams(reference_dir)
    db.replace_table("dim_team", ref[["team_id", "name", "is_own"]])

    names = db.query_df("""
        SELECT 'A' AS source, home_team AS name FROM stg_a_matches
        UNION SELECT 'A', away_team FROM stg_a_matches
        UNION SELECT 'B', home_team FROM stg_b_matches
        UNION SELECT 'B', away_team FROM stg_b_matches
    """)
    rows, mapping = [], {}
    for r in names.itertuples():
        team_id, method = match_team(r.name, teams)
        mapping[(r.source, r.name)] = team_id
        rows.append({"source": r.source, "source_name": r.name, "team_id": team_id, "method": method})
    db.replace_table("map_team", pd.DataFrame(rows))
    return mapping


def build_players(db: Database, team_map: dict[tuple[str, str], int | None]) -> dict[tuple[str, str], int | None]:
    a = db.query_df("""
        SELECT player_id, player_name, team, jersey, COUNT(*) AS n
        FROM stg_a_lineups GROUP BY player_id, player_name, team, jersey
    """)
    # A player can appear with several jerseys/names across files; keep the most frequent spelling.
    a = a.sort_values("n", ascending=False).drop_duplicates("player_id").sort_values("player_id")
    a["team_id"] = [team_map.get(("A", t)) for t in a["team"]]
    a = a[a["team_id"].notna()]
    a["canonical_id"] = range(1, len(a) + 1)

    birth = db.query_df("SELECT player_key, MAX(birth_date) AS birth_date FROM stg_b_player_stats GROUP BY player_key")

    dim = pd.DataFrame({
        "player_id": a["canonical_id"],
        "full_name": a["player_name"],
        "team_id": a["team_id"].astype(int),
        "jersey": a["jersey"],
        "birth_date": None,
    })
    candidates = [Candidate(int(r.canonical_id), r.player_name, int(r.team_id), int(r.jersey))
                  for r in a.itertuples()]

    rows = [{"source": "A", "source_key": str(r.player_id), "source_name": r.player_name,
             "player_id": int(r.canonical_id), "method": "master", "score": 1.0} for r in a.itertuples()]

    b = db.query_df("""
        SELECT player_key, full_name, team, MAX(jersey) AS jersey
        FROM stg_b_player_stats GROUP BY player_key, full_name, team
    """)
    for r in b.itertuples():
        res = match_player(r.full_name, team_map.get(("B", r.team)), _int(r.jersey), candidates)
        rows.append({"source": "B", "source_key": r.player_key, "source_name": r.full_name,
                     "player_id": res.player_id, "method": res.method, "score": res.score})

    gps = db.query_df("SELECT DISTINCT athlete, jersey FROM stg_gps")
    for r in gps.itertuples():
        key = f"{r.athlete}#{r.jersey}"
        res = match_player(r.athlete, OWN_TEAM_ID, _int(r.jersey), candidates)
        rows.append({"source": "GPS", "source_key": key, "source_name": r.athlete,
                     "player_id": res.player_id, "method": res.method, "score": res.score})

    mp = pd.DataFrame(rows)
    # Enrich the master with birth dates that only provider B knows.
    b_birth = mp[(mp.source == "B") & mp.player_id.notna()].merge(
        birth, left_on="source_key", right_on="player_key")[["player_id", "birth_date"]]
    dim = dim.drop(columns="birth_date").merge(
        b_birth.drop_duplicates("player_id"), on="player_id", how="left")

    db.replace_table("dim_player", dim)
    db.replace_table("map_player", mp)
    return {(r.source, r.source_key): (None if pd.isna(r.player_id) else int(r.player_id))
            for r in mp.itertuples()}


def build_matches(db: Database, team_map: dict) -> dict[str, int]:
    a = db.query_df("SELECT DISTINCT match_id, match_date, home_team, away_team FROM stg_a_matches ORDER BY match_date")
    b = db.query_df("SELECT DISTINCT match_id, match_date, home_team, away_team FROM stg_b_matches")
    b["home_id"] = [team_map.get(("B", t)) for t in b["home_team"]]
    b["away_id"] = [team_map.get(("B", t)) for t in b["away_team"]]
    b_index = {(str(r.match_date), r.home_id, r.away_id): r.match_id for r in b.itertuples()}

    rows = []
    for i, r in enumerate(a.itertuples(), start=1):
        home, away = team_map.get(("A", r.home_team)), team_map.get(("A", r.away_team))
        rows.append({"match_id": i, "match_date": str(r.match_date), "home_team_id": home, "away_team_id": away,
                     "a_match_id": r.match_id, "b_match_id": b_index.get((str(r.match_date), home, away))})
    dim = pd.DataFrame(rows)
    db.replace_table("dim_match", dim)
    return dict(zip(dim["a_match_id"], dim["match_id"]))


def build_events(db: Database, match_map: dict, team_map: dict, player_map: dict) -> int:
    ev = db.query_df("SELECT * FROM stg_a_events")
    before = len(ev)
    ev = ev.sort_values("event_id").drop_duplicates(EVENT_NATURAL_KEY, keep="first")
    log.info("transform: events deduplicated %d -> %d", before, len(ev))
    out = pd.DataFrame({
        "event_id": ev["event_id"],
        "match_id": ev["match_id"].map(match_map),
        "period": ev["period"],
        "minute": ev["minute"],
        "second": ev["second"],
        "event_type": ev["event_type"],
        "team_id": [team_map.get(("A", t)) for t in ev["team"]],
        "player_id": [None if pd.isna(p) else player_map.get(("A", str(int(p)))) for p in ev["player_id"]],
        "outcome": ev["outcome"],
        "xg": ev["xg"],
    })
    return db.replace_table("fact_event", out)


def build_lineups(db: Database, match_map: dict, team_map: dict, player_map: dict) -> int:
    lu = db.query_df("SELECT match_id, player_id, team, minutes FROM stg_a_lineups")
    out = pd.DataFrame({
        "match_id": lu["match_id"].map(match_map),
        "player_id": [player_map.get(("A", str(p))) for p in lu["player_id"]],
        "team_id": [team_map.get(("A", t)) for t in lu["team"]],
        "minutes": lu["minutes"],
    }).dropna(subset=["player_id", "team_id"]).drop_duplicates(["match_id", "player_id"])
    return db.replace_table("fact_lineup", out)


def build_gps(db: Database, player_map: dict) -> int:
    g = db.query_df("""SELECT session_date, session_type, athlete, jersey, duration_min, total_distance_m,
                              hsr_m, sprints, max_speed_kmh FROM stg_gps""")
    data_cols = [c for c in g.columns]
    before = len(g)
    g = g.drop_duplicates(data_cols)
    log.info("transform: gps deduplicated %d -> %d", before, len(g))

    reasons = []
    for r in g.itertuples():
        if r.max_speed_kmh is not None and (r.max_speed_kmh > MAX_HUMAN_SPEED_KMH or r.max_speed_kmh < 0):
            reasons.append("impossible_speed")
        elif r.duration_min > DROPOUT_MIN_DURATION and r.total_distance_m < DROPOUT_MAX_DISTANCE:
            reasons.append("dropout")
        else:
            reasons.append(None)
    out = pd.DataFrame({
        "session_date": g["session_date"].astype(str),
        "session_type": g["session_type"],
        "player_id": [player_map.get(("GPS", f"{a}#{j}")) for a, j in zip(g["athlete"], g["jersey"])],
        "duration_min": g["duration_min"],
        "total_distance_m": g["total_distance_m"],
        "hsr_m": g["hsr_m"],
        "sprints": g["sprints"],
        "max_speed_kmh": g["max_speed_kmh"],
        "is_valid": [0 if x else 1 for x in reasons],
        "invalid_reason": reasons,
    })
    return db.replace_table("fact_gps", out)


def build_dates(db: Database) -> int:
    lo = db.scalar("SELECT MIN(d) FROM (SELECT MIN(session_date) AS d FROM stg_gps UNION ALL SELECT MIN(match_date) FROM stg_a_matches) x")
    hi = db.scalar("SELECT MAX(d) FROM (SELECT MAX(session_date) AS d FROM stg_gps UNION ALL SELECT MAX(match_date) FROM stg_a_matches) x")
    days = pd.date_range(str(lo), str(hi), freq="D")
    epoch = date(1970, 1, 1)
    df = pd.DataFrame({"date_day": [d.date().isoformat() for d in days],
                       "day_idx": [(d.date() - epoch).days for d in days]})
    return db.replace_table("dim_date", df)


def run(db: Database, reference_dir: Path) -> dict[str, int]:
    with db.transaction():
        team_map = build_teams(db, reference_dir)
        player_map = build_players(db, team_map)
        match_map = build_matches(db, team_map)
        counts = {
            "fact_event": build_events(db, match_map, team_map, player_map),
            "fact_lineup": build_lineups(db, match_map, team_map, player_map),
            "fact_gps": build_gps(db, player_map),
            "dim_date": build_dates(db),
        }
    return counts


def _int(v) -> int | None:
    return None if v is None or pd.isna(v) else int(v)
