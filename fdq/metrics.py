"""Training load metrics: two ways to compute the acute:chronic workload ratio.

ACWR = recent load (acute, ~1 week) / habitual load (chronic, ~4 weeks).
Values far above ~1.3-1.5 mean a spike relative to what the player is used to.

* rolling: plain 7-day and 28-day averages (in SQL, view mart_player_load_daily).
  Simple and explainable, but every day in the window weighs the same, and a
  big session counts fully until the day it drops out of the window.
* EWMA: exponentially weighted averages (Williams et al., 2017). Recent days
  weigh more, the effect decays smoothly. lambda = 2 / (N + 1).

docs/metrics.md compares both on our data.
"""

from __future__ import annotations

import pandas as pd

from .db import Database


def ewma(series: pd.Series, span_days: int) -> pd.Series:
    alpha = 2 / (span_days + 1)
    return series.ewm(alpha=alpha, adjust=False).mean()


def build_player_load(db: Database) -> int:
    daily = db.query_df("""
        SELECT player_id, full_name, date_day, distance_m, acute_7d, chronic_28d, days_in_chronic
        FROM mart_player_load_daily ORDER BY player_id, date_day
    """)
    if daily.empty:
        return 0
    parts = []
    for _, g in daily.groupby("player_id", sort=False):
        g = g.copy()
        # The ratio is meaningless until a full chronic window exists.
        full = g["days_in_chronic"] >= 28
        g["acwr_rolling"] = (g["acute_7d"] / g["chronic_28d"]).where(full & (g["chronic_28d"] > 0))
        acute, chronic = ewma(g["distance_m"], 7), ewma(g["distance_m"], 28)
        g["acwr_ewma"] = (acute / chronic).where(full & (chronic > 0))
        parts.append(g)
    out = pd.concat(parts)[["player_id", "full_name", "date_day", "distance_m",
                            "acute_7d", "chronic_28d", "acwr_rolling", "acwr_ewma"]]
    out["date_day"] = out["date_day"].astype(str)
    with db.transaction():
        return db.replace_table("mart_player_load", out)
