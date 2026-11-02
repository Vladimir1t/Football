-- Data marts: the backend for BI dashboards (DataLens / Metabase / Superset).
-- Views, so they are always consistent with core. Portable SQLite / PostgreSQL.
-- Rounding is left to the BI layer (ROUND(double, int) does not exist in PostgreSQL).

-- Player x match: attacking output from events + physical output from GPS.
DROP VIEW IF EXISTS mart_player_match;
CREATE VIEW mart_player_match AS
WITH ev AS (
    SELECT
        match_id,
        player_id,
        SUM(CASE WHEN event_type = 'shot' THEN 1 ELSE 0 END)                         AS shots,
        SUM(CASE WHEN event_type = 'shot' AND outcome = 'goal' THEN 1 ELSE 0 END)    AS goals,
        SUM(CASE WHEN event_type = 'shot' THEN xg ELSE 0 END)                         AS xg,
        SUM(CASE WHEN event_type = 'pass' THEN 1 ELSE 0 END)                          AS passes,
        SUM(CASE WHEN event_type = 'pass' AND outcome = 'complete' THEN 1 ELSE 0 END) AS passes_completed
    FROM fact_event
    WHERE player_id IS NOT NULL
    GROUP BY match_id, player_id
),
gps AS (
    SELECT player_id, session_date, SUM(total_distance_m) AS distance_m, SUM(hsr_m) AS hsr_m,
           MAX(max_speed_kmh) AS max_speed_kmh
    FROM fact_gps
    WHERE session_type = 'match' AND is_valid = 1
    GROUP BY player_id, session_date
)
SELECT
    m.match_id,
    m.match_date,
    t.name                                                   AS team,
    p.player_id,
    p.full_name,
    l.minutes,
    COALESCE(ev.shots, 0)                                    AS shots,
    COALESCE(ev.goals, 0)                                    AS goals,
    COALESCE(ev.xg, 0)                                       AS xg,
    COALESCE(ev.passes, 0)                                   AS passes,
    1.0 * ev.passes_completed / NULLIF(ev.passes, 0)         AS pass_accuracy,
    90.0 * COALESCE(ev.xg, 0) / NULLIF(l.minutes, 0)         AS xg_per90,
    gps.distance_m,
    gps.hsr_m,
    gps.max_speed_kmh,
    1.0 * gps.distance_m / NULLIF(l.minutes, 0)              AS metres_per_min
FROM fact_lineup l
JOIN dim_match  m ON m.match_id = l.match_id
JOIN dim_player p ON p.player_id = l.player_id
JOIN dim_team   t ON t.team_id = l.team_id
LEFT JOIN ev  ON ev.match_id = l.match_id AND ev.player_id = l.player_id
LEFT JOIN gps ON gps.player_id = l.player_id AND gps.session_date = m.match_date;

-- Match reconciliation between providers: the first thing to look at when numbers "don't add up".
DROP VIEW IF EXISTS mart_match_reconciliation;
CREATE VIEW mart_match_reconciliation AS
WITH a AS (
    SELECT
        e.match_id,
        SUM(CASE WHEN e.team_id = m.home_team_id AND e.event_type = 'shot' AND e.outcome = 'goal' THEN 1 ELSE 0 END) AS a_home_goals,
        SUM(CASE WHEN e.team_id = m.away_team_id AND e.event_type = 'shot' AND e.outcome = 'goal' THEN 1 ELSE 0 END) AS a_away_goals,
        SUM(CASE WHEN e.team_id = m.home_team_id AND e.event_type = 'shot' THEN 1 ELSE 0 END)                       AS a_home_shots,
        SUM(CASE WHEN e.team_id = m.away_team_id AND e.event_type = 'shot' THEN 1 ELSE 0 END)                       AS a_away_shots
    FROM fact_event e
    JOIN dim_match m ON m.match_id = e.match_id
    GROUP BY e.match_id
)
SELECT
    m.match_id,
    m.match_date,
    th.name AS home_team,
    ta.name AS away_team,
    m.a_match_id,
    m.b_match_id,
    a.a_home_goals, b.home_goals AS b_home_goals,
    a.a_away_goals, b.away_goals AS b_away_goals,
    a.a_home_shots, b.home_shots AS b_home_shots,
    a.a_away_shots, b.away_shots AS b_away_shots,
    CASE
        WHEN m.b_match_id IS NULL THEN 'missing_in_b'
        WHEN a.a_home_goals <> b.home_goals OR a.a_away_goals <> b.away_goals THEN 'score_mismatch'
        WHEN ABS(a.a_home_shots - b.home_shots) > 2 OR ABS(a.a_away_shots - b.away_shots) > 2 THEN 'shots_mismatch'
        ELSE 'ok'
    END AS status
FROM dim_match m
JOIN dim_team th ON th.team_id = m.home_team_id
JOIN dim_team ta ON ta.team_id = m.away_team_id
LEFT JOIN a ON a.match_id = m.match_id
LEFT JOIN stg_b_matches b ON b.match_id = m.b_match_id;

-- Daily load per player of our team on a complete calendar: rest days count as zero load,
-- otherwise rolling averages would silently skip them and overstate the load.
DROP VIEW IF EXISTS mart_player_load_daily;
CREATE VIEW mart_player_load_daily AS
WITH grid AS (
    SELECT p.player_id, p.full_name, d.date_day
    FROM dim_player p
    JOIN dim_team t ON t.team_id = p.team_id AND t.is_own = 1
    CROSS JOIN dim_date d
),
daily AS (
    SELECT g.player_id, g.full_name, g.date_day,
           COALESCE(SUM(f.total_distance_m), 0) AS distance_m,
           COALESCE(SUM(f.hsr_m), 0)            AS hsr_m,
           COUNT(f.player_id)                   AS sessions
    FROM grid g
    LEFT JOIN fact_gps f ON f.player_id = g.player_id AND f.session_date = g.date_day AND f.is_valid = 1
    GROUP BY g.player_id, g.full_name, g.date_day
)
SELECT
    player_id, full_name, date_day, distance_m, hsr_m, sessions,
    AVG(distance_m) OVER w7  AS acute_7d,
    AVG(distance_m) OVER w28 AS chronic_28d,
    COUNT(*)        OVER w28 AS days_in_chronic
FROM daily
WINDOW
    w7  AS (PARTITION BY player_id ORDER BY date_day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
    w28 AS (PARTITION BY player_id ORDER BY date_day ROWS BETWEEN 27 PRECEDING AND CURRENT ROW);

-- One row per DQ run and check, for a "data health" dashboard.
DROP VIEW IF EXISTS mart_dq_history;
CREATE VIEW mart_dq_history AS
SELECT r.started_at, d.run_id, d.check_name, d.category, d.severity, d.status, d.failed_rows
FROM dq_result d
JOIN dq_run r ON r.run_id = d.run_id;
