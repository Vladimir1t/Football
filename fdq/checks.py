"""Data quality checks.

Every check is a SQL query that returns the *violating* rows: zero rows = pass.
This keeps checks readable, testable one by one, and easy to copy into dbt
tests or Soda later (see docs/TASKS.md).

Categories follow the usual DQ dimensions: completeness, uniqueness, validity,
consistency (between sources), freshness, anomaly.
Severity: "error" = numbers in reports would be wrong; "warn" = needs a look.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import OWN_TEAM_ID


@dataclass(frozen=True)
class Check:
    name: str
    category: str
    severity: str
    description: str
    sql: str
    params: Callable[[dict], list] = field(default=lambda ctx: [])


CHECKS: list[Check] = [
    # ---------------------------------------------------------------- uniqueness
    Check(
        "events_duplicates", "uniqueness", "warn",
        "Поставщик A прислал одно событие несколько раз под разными ID (повторная отправка). В core дубли удалены.",
        """
        SELECT match_id, period, minute, second, event_type, team, player_id, COUNT(*) AS copies
        FROM stg_a_events
        GROUP BY match_id, period, minute, second, event_type, team, player_id
        HAVING COUNT(*) > 1
        """,
    ),
    Check(
        "gps_duplicates", "uniqueness", "warn",
        "Одинаковые строки GPS (сессию выгрузили дважды). В core дубли удалены.",
        """
        SELECT session_date, athlete, session_type, total_distance_m, COUNT(*) AS copies
        FROM stg_gps
        GROUP BY session_date, session_type, athlete, jersey, duration_min, total_distance_m,
                 hsr_m, sprints, max_speed_kmh
        HAVING COUNT(*) > 1
        """,
    ),
    # ---------------------------------------------------------------- completeness
    Check(
        "events_missing_player", "completeness", "error",
        "События без игрока: они выпадают из всех метрик по игрокам.",
        "SELECT event_id, match_id, minute, event_type FROM stg_a_events WHERE player_id IS NULL",
    ),
    Check(
        "match_missing_in_provider_b", "completeness", "error",
        "Матч пришёл от поставщика A, но не от поставщика B (поставка опоздала или потерялась).",
        "SELECT match_date, a_match_id FROM dim_match WHERE b_match_id IS NULL",
    ),
    Check(
        "gps_missing_for_match", "completeness", "error",
        "Наш игрок играл в матче, но GPS-сессии за этот день нет.",
        """
        SELECT m.match_date, p.full_name, l.minutes
        FROM fact_lineup l
        JOIN dim_match m  ON m.match_id = l.match_id
        JOIN dim_player p ON p.player_id = l.player_id
        WHERE l.team_id = ? AND l.minutes > 0
          AND NOT EXISTS (
              SELECT 1 FROM fact_gps g
              WHERE g.player_id = l.player_id AND g.session_date = m.match_date
          )
        """,
        params=lambda ctx: [OWN_TEAM_ID],
    ),
    Check(
        "unmapped_teams", "completeness", "error",
        "Название команды от поставщика не найдено в reference/teams.csv: добавьте алиас.",
        "SELECT source, source_name FROM map_team WHERE team_id IS NULL",
    ),
    Check(
        "unmatched_players", "completeness", "warn",
        "Игроки поставщика B или GPS, не сопоставленные с мастер-списком. Нужна ручная проверка.",
        "SELECT source, source_key, source_name, score FROM map_player WHERE player_id IS NULL",
    ),
    # ---------------------------------------------------------------- validity
    Check(
        "events_minute_out_of_range", "validity", "error",
        "Минута события вне 0..130 (90 + добавленное + дополнительное время).",
        "SELECT event_id, match_id, minute FROM stg_a_events WHERE minute < 0 OR minute > 130",
    ),
    Check(
        "shots_xg_out_of_range", "validity", "error",
        "xG — вероятность, значение должно быть в [0, 1].",
        """
        SELECT event_id, match_id, xg FROM stg_a_events
        WHERE event_type = 'shot' AND (xg IS NULL OR xg < 0 OR xg > 1)
        """,
    ),
    Check(
        "gps_impossible_speed", "validity", "error",
        "Максимальная скорость выше 38 км/ч или отрицательная: ошибка датчика. Строка исключена из метрик нагрузки.",
        "SELECT session_date, player_id, max_speed_kmh FROM fact_gps WHERE invalid_reason = 'impossible_speed'",
    ),
    Check(
        "gps_dropout", "validity", "error",
        "Долгая сессия почти без дистанции: датчик разрядился или не был надет. Исключена из метрик нагрузки.",
        """
        SELECT session_date, player_id, duration_min, total_distance_m
        FROM fact_gps WHERE invalid_reason = 'dropout'
        """,
    ),
    # ---------------------------------------------------------------- consistency
    Check(
        "score_mismatch_between_providers", "consistency", "error",
        "Голы по событиям поставщика A не совпадают с итоговым счётом поставщика B.",
        """
        SELECT match_date, home_team, away_team, a_home_goals, b_home_goals, a_away_goals, b_away_goals
        FROM mart_match_reconciliation WHERE status = 'score_mismatch'
        """,
    ),
    Check(
        "shots_mismatch_between_providers", "consistency", "warn",
        "Удары расходятся больше чем на 2. Небольшая разница ожидаема: B считает и заблокированные удары.",
        """
        SELECT match_date, home_team, away_team, a_home_shots, b_home_shots, a_away_shots, b_away_shots
        FROM mart_match_reconciliation
        WHERE b_match_id IS NOT NULL
          AND (ABS(a_home_shots - b_home_shots) > 2 OR ABS(a_away_shots - b_away_shots) > 2)
        """,
    ),
    Check(
        "minutes_mismatch_between_providers", "consistency", "warn",
        "Сыгранные минуты расходятся больше чем на 2 (разница в 1 минуту — округление).",
        """
        SELECT m.match_date, p.full_name, l.minutes AS a_minutes, b.minutes AS b_minutes
        FROM stg_b_player_stats b
        JOIN map_player mp ON mp.source = 'B' AND mp.source_key = b.player_key AND mp.player_id IS NOT NULL
        JOIN dim_match m   ON m.b_match_id = b.match_id
        JOIN fact_lineup l ON l.match_id = m.match_id AND l.player_id = mp.player_id
        JOIN dim_player p  ON p.player_id = mp.player_id
        WHERE ABS(l.minutes - b.minutes) > 2
        """,
    ),
    # ---------------------------------------------------------------- freshness
    Check(
        "gps_freshness", "freshness", "error",
        "Нет GPS-данных за последние 3 дня: вероятно, выгрузка из GPS-системы остановилась.",
        """
        SELECT last_session FROM (SELECT MAX(session_date) AS last_session FROM stg_gps) x
        WHERE last_session IS NULL OR last_session < ?
        """,
        params=lambda ctx: [ctx["freshness_cutoff"]],
    ),
    # ---------------------------------------------------------------- anomaly
    Check(
        "gps_distance_anomaly", "anomaly", "warn",
        "Тренировочная дистанция дальше 3 стандартных отклонений от собственной нормы игрока.",
        # z-score without SQRT (not available everywhere): (x - mean)^2 > 9 * variance.
        """
        WITH s AS (
            SELECT player_id,
                   AVG(total_distance_m) AS mean_d,
                   AVG(total_distance_m * total_distance_m) - AVG(total_distance_m) * AVG(total_distance_m) AS var_d,
                   COUNT(*) AS n
            FROM fact_gps
            WHERE is_valid = 1 AND session_type = 'training'
            GROUP BY player_id
        )
        SELECT g.session_date, p.full_name, g.total_distance_m, s.mean_d
        FROM fact_gps g
        JOIN s ON s.player_id = g.player_id
        JOIN dim_player p ON p.player_id = g.player_id
        WHERE g.is_valid = 1 AND g.session_type = 'training' AND s.n >= 10
          AND (g.total_distance_m - s.mean_d) * (g.total_distance_m - s.mean_d) > 9 * s.var_d
        """,
    ),
]
