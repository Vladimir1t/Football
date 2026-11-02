# Отчёт о качестве данных

Запуск `20261102T082747-6e0480` · 2026-11-02T08:27:47+00:00 · **ошибок: 8**, **предупреждений: 4**, проверок: 16

## Загружено строк

| Таблица | Строк |
|---|---|
| stg_a_matches | 10 |
| stg_a_lineups | 267 |
| stg_a_events | 8524 |
| stg_b_matches | 9 |
| stg_b_player_stats | 241 |
| stg_gps | 1368 |
| fact_event | 8519 |
| fact_lineup | 267 |
| fact_gps | 1367 |
| dim_date | 92 |
| mart_player_load | 1564 |

## Проверки

| Статус | Уровень | Измерение | Проверка | Строк-нарушений |
|---|---|---|---|---|
| ❌ | error | validity | `events_minute_out_of_range` | 1 |
| ❌ | error | completeness | `events_missing_player` | 4 |
| ❌ | error | validity | `gps_dropout` | 1 |
| ❌ | error | validity | `gps_impossible_speed` | 1 |
| ❌ | error | completeness | `gps_missing_for_match` | 1 |
| ❌ | error | completeness | `match_missing_in_provider_b` | 1 |
| ❌ | error | consistency | `score_mismatch_between_providers` | 1 |
| ❌ | error | validity | `shots_xg_out_of_range` | 1 |
| ⚠️ | warn | uniqueness | `events_duplicates` | 5 |
| ⚠️ | warn | anomaly | `gps_distance_anomaly` | 1 |
| ⚠️ | warn | uniqueness | `gps_duplicates` | 1 |
| ⚠️ | warn | completeness | `unmatched_players` | 2 |
| ✅ | error | freshness | `gps_freshness` | 0 |
| ✅ | error | completeness | `unmapped_teams` | 0 |
| ✅ | warn | consistency | `minutes_mismatch_between_providers` | 0 |
| ✅ | warn | consistency | `shots_mismatch_between_providers` | 0 |

## Подробности

### `events_duplicates`

Поставщик A прислал одно событие несколько раз под разными ID (повторная отправка). В core дубли удалены.

| match_id | period | minute | second | event_type | team | player_id | copies |
|---|---|---|---|---|---|---|---|
| A-1003 | 1 | 9 | 41 | pass | FC Volna | 413 | 2 |
| A-1003 | 1 | 17 | 12 | pass | FC Volna | 407 | 2 |
| A-1003 | 1 | 22 | 19 | pass | FC Sokol | 112 | 2 |
| A-1003 | 1 | 31 | 33 | pass | FC Volna | 402 | 2 |
| A-1003 | 2 | 88 | 43 | pass | FC Volna | 410 | 2 |

### `gps_duplicates`

Одинаковые строки GPS (сессию выгрузили дважды). В core дубли удалены.

| session_date | athlete | session_type | total_distance_m | copies |
|---|---|---|---|---|
| 2026-07-24 | А. Соколов | training | 5128.0 | 2 |

### `events_missing_player`

События без игрока: они выпадают из всех метрик по игрокам.

| event_id | match_id | minute | event_type |
|---|---|---|---|
| A-1005-00535 | A-1005 | 12 | pass |
| A-1005-00225 | A-1005 | 55 | pass |
| A-1005-00516 | A-1005 | 55 | pass |
| A-1005-00686 | A-1005 | 78 | pass |

### `match_missing_in_provider_b`

Матч пришёл от поставщика A, но не от поставщика B (поставка опоздала или потерялась).

| match_date | a_match_id |
|---|---|
| 2026-10-03 | A-1010 |

### `gps_missing_for_match`

Наш игрок играл в матче, но GPS-сессии за этот день нет.

| match_date | full_name | minutes |
|---|---|---|
| 2026-08-22 | Sergei Kiselyov | 90 |

### `unmatched_players`

Игроки поставщика B или GPS, не сопоставленные с мастер-списком. Нужна ручная проверка.

| source | source_key | source_name | score |
|---|---|---|---|
| B | SH-P9999 | Новенький Арсений | 0.414 |
| GPS | К. Павлов#37 | К. Павлов | 0.509 |

### `events_minute_out_of_range`

Минута события вне 0..130 (90 + добавленное + дополнительное время).

| event_id | match_id | minute |
|---|---|---|
| A-1002-00123 | A-1002 | 135 |

### `shots_xg_out_of_range`

xG — вероятность, значение должно быть в [0, 1].

| event_id | match_id | xg |
|---|---|---|
| A-1002-00075 | A-1002 | 1.35 |

### `gps_impossible_speed`

Максимальная скорость выше 38 км/ч или отрицательная: ошибка датчика. Строка исключена из метрик нагрузки.

| session_date | player_id | max_speed_kmh |
|---|---|---|
| 2026-07-14 | 1 | 52.4 |

### `gps_dropout`

Долгая сессия почти без дистанции: датчик разрядился или не был надет. Исключена из метрик нагрузки.

| session_date | player_id | duration_min | total_distance_m |
|---|---|---|---|
| 2026-08-08 | 7 | 95.0 | 0.0 |

### `score_mismatch_between_providers`

Голы по событиям поставщика A не совпадают с итоговым счётом поставщика B.

| match_date | home_team | away_team | a_home_goals | b_home_goals | a_away_goals | b_away_goals |
|---|---|---|---|---|---|---|
| 2026-09-05 | Звезда | Сокол | 1 | 2 | 0 | 0 |

### `gps_distance_anomaly`

Тренировочная дистанция дальше 3 стандартных отклонений от собственной нормы игрока.

| session_date | full_name | total_distance_m | mean_d |
|---|---|---|---|
| 2026-09-09 | Egor Fomin | 16544.0 | 5738.623188405797 |
