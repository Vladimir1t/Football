"""A thin database layer that works with SQLite (default) and PostgreSQL.

All SQL in the project is written to run on both: `?` placeholders (rewritten
to `%s` for psycopg), COALESCE instead of IFNULL, no ROUND on floats, dates
compared as ISO strings.
"""

from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np
import pandas as pd


def _py(value: Any) -> Any:
    """Convert pandas/numpy scalars to plain Python values the drivers understand."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, np.generic):
        value = value.item()
        if isinstance(value, float) and math.isnan(value):
            return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return value


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        if url.startswith("sqlite:///"):
            path = Path(url[len("sqlite:///") :])
            path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(path)
            self.dialect = "sqlite"
        elif url.startswith(("postgresql://", "postgres://")):
            import psycopg  # optional dependency: pip install -r requirements-postgres.txt

            self.conn = psycopg.connect(url)
            self.dialect = "postgres"
        else:
            raise ValueError(f"unsupported database url: {url}")

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self.conn.cursor()
        cur.execute(self._sql(sql), [_py(p) for p in params])
        return cur

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        cur = self.conn.cursor()
        cur.executemany(self._sql(sql), [[_py(v) for v in row] for row in rows])

    def executescript(self, script: str) -> None:
        if self.dialect == "sqlite":
            self.conn.executescript(script)
        else:
            self.conn.cursor().execute(script)  # psycopg runs several statements without params

    def query_df(self, sql: str, params: Sequence[Any] = ()) -> pd.DataFrame:
        cur = self.execute(sql, params)
        columns = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.execute(sql, params).fetchone()
        return row[0] if row else None

    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        cols = list(df.columns)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        self.executemany(sql, df.itertuples(index=False, name=None))
        return len(df)

    def replace_table(self, table: str, df: pd.DataFrame) -> int:
        """Full refresh of a derived table inside the current transaction."""
        self.execute(f"DELETE FROM {table}")
        return self.insert_df(table, df)

    @contextmanager
    def transaction(self) -> Iterator["Database"]:
        try:
            yield self
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self) -> None:
        self.conn.close()
