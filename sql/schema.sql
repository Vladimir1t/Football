-- Portable schema: runs on SQLite and PostgreSQL.
-- Layers: stg_* (as delivered) -> core (dim_*/map_*/fact_*) -> marts (sql/marts.sql) ; dq_* (quality results).

-- ============================== staging ==============================
-- Provider A ("EventPro"): event data, one JSON file per match, Latin names.
CREATE TABLE IF NOT EXISTS stg_a_matches (
    match_id    TEXT NOT NULL,
    match_date  DATE NOT NULL,
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    _file       TEXT NOT NULL,
    _loaded_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_a_lineups (
    match_id    TEXT NOT NULL,
    player_id   INTEGER NOT NULL,
    player_name TEXT NOT NULL,
    team        TEXT NOT NULL,
    jersey      INTEGER,
    minutes     INTEGER,
    _file       TEXT NOT NULL,
    _loaded_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_a_events (
    event_id    TEXT NOT NULL,
    match_id    TEXT NOT NULL,
    period      INTEGER,
    minute      INTEGER,
    second      INTEGER,
    event_type  TEXT,
    team        TEXT,
    player_id   INTEGER,
    outcome     TEXT,
    xg          REAL,
    _file       TEXT NOT NULL,
    _loaded_at  TEXT NOT NULL
);

-- Provider B ("StatHub"): aggregated match and player stats, CSV, Cyrillic names.
CREATE TABLE IF NOT EXISTS stg_b_matches (
    match_id    TEXT NOT NULL,
    match_date  DATE NOT NULL,
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    home_goals  INTEGER,
    away_goals  INTEGER,
    home_shots  INTEGER,
    away_shots  INTEGER,
    _file       TEXT NOT NULL,
    _loaded_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stg_b_player_stats (
    match_id    TEXT NOT NULL,
    player_key  TEXT NOT NULL,
    full_name   TEXT NOT NULL,
    birth_date  DATE,
    team        TEXT NOT NULL,
    jersey      INTEGER,
    minutes     INTEGER,
    goals       INTEGER,
    shots       INTEGER,
    _file       TEXT NOT NULL,
    _loaded_at  TEXT NOT NULL
);

-- Internal GPS system: one CSV per day, our team only, athlete = "И. Петров" + jersey.
CREATE TABLE IF NOT EXISTS stg_gps (
    session_date     DATE NOT NULL,
    session_type     TEXT NOT NULL,
    athlete          TEXT NOT NULL,
    jersey           INTEGER,
    duration_min     REAL,
    total_distance_m REAL,
    hsr_m            REAL,
    sprints          INTEGER,
    max_speed_kmh    REAL,
    _file            TEXT NOT NULL,
    _loaded_at       TEXT NOT NULL
);

-- ============================== core ==============================
CREATE TABLE IF NOT EXISTS dim_team (
    team_id  INTEGER PRIMARY KEY,
    name     TEXT NOT NULL,
    is_own   INTEGER NOT NULL DEFAULT 0
);

-- Source-specific team names -> canonical team.
CREATE TABLE IF NOT EXISTS map_team (
    source       TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    team_id      INTEGER,          -- NULL = could not be mapped (DQ check)
    method       TEXT NOT NULL,
    PRIMARY KEY (source, source_name)
);

CREATE TABLE IF NOT EXISTS dim_player (
    player_id  INTEGER PRIMARY KEY,
    full_name  TEXT NOT NULL,
    team_id    INTEGER NOT NULL,
    jersey     INTEGER,
    birth_date DATE
);

-- Source-specific player keys -> canonical player. Provider A is the master.
CREATE TABLE IF NOT EXISTS map_player (
    source       TEXT NOT NULL,
    source_key   TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    player_id    INTEGER,          -- NULL = unmatched, goes to manual review
    method       TEXT NOT NULL,    -- master | team+jersey | name_fuzzy | unmatched
    score        REAL,
    PRIMARY KEY (source, source_key)
);

CREATE TABLE IF NOT EXISTS dim_match (
    match_id      INTEGER PRIMARY KEY,
    match_date    DATE NOT NULL,
    home_team_id  INTEGER,
    away_team_id  INTEGER,
    a_match_id    TEXT NOT NULL,
    b_match_id    TEXT              -- NULL = provider B has not delivered this match
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_day  DATE PRIMARY KEY,
    day_idx   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_event (
    event_id    TEXT PRIMARY KEY,
    match_id    INTEGER NOT NULL,
    period      INTEGER,
    minute      INTEGER,
    second      INTEGER,
    event_type  TEXT,
    team_id     INTEGER,
    player_id   INTEGER,
    outcome     TEXT,
    xg          REAL
);

CREATE TABLE IF NOT EXISTS fact_lineup (
    match_id   INTEGER NOT NULL,
    player_id  INTEGER NOT NULL,
    team_id    INTEGER NOT NULL,
    minutes    INTEGER,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE IF NOT EXISTS fact_gps (
    session_date     DATE NOT NULL,
    session_type     TEXT NOT NULL,
    player_id        INTEGER,
    duration_min     REAL,
    total_distance_m REAL,
    hsr_m            REAL,
    sprints          INTEGER,
    max_speed_kmh    REAL,
    is_valid         INTEGER NOT NULL,
    invalid_reason   TEXT
);

-- Daily load with both ACWR variants (written by fdq/metrics.py).
CREATE TABLE IF NOT EXISTS mart_player_load (
    player_id        INTEGER NOT NULL,
    full_name        TEXT NOT NULL,
    date_day         DATE NOT NULL,
    distance_m       REAL NOT NULL,
    acute_7d         REAL,
    chronic_28d      REAL,
    acwr_rolling     REAL,
    acwr_ewma        REAL,
    PRIMARY KEY (player_id, date_day)
);

-- ============================== data quality ==============================
CREATE TABLE IF NOT EXISTS dq_run (
    run_id       TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    n_checks     INTEGER,
    n_errors     INTEGER,
    n_warnings   INTEGER
);

CREATE TABLE IF NOT EXISTS dq_result (
    run_id       TEXT NOT NULL,
    check_name   TEXT NOT NULL,
    category     TEXT NOT NULL,
    severity     TEXT NOT NULL,
    status       TEXT NOT NULL,   -- pass | fail
    failed_rows  INTEGER NOT NULL,
    sample       TEXT,            -- first rows as JSON, for the report
    description  TEXT NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

CREATE INDEX IF NOT EXISTS stg_a_events_file_idx ON stg_a_events (_file);
CREATE INDEX IF NOT EXISTS fact_event_match_idx ON fact_event (match_id, player_id);
CREATE INDEX IF NOT EXISTS fact_gps_player_date_idx ON fact_gps (player_id, session_date);
