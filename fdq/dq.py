"""Runs the checks, stores results in dq_run / dq_result, writes a report, sends an alert."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .checks import CHECKS, Check
from .db import Database

log = logging.getLogger(__name__)

SAMPLE_ROWS = 5


@dataclass
class CheckResult:
    check: Check
    failed_rows: int
    sample: pd.DataFrame

    @property
    def status(self) -> str:
        return "pass" if self.failed_rows == 0 else "fail"


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    results: list[CheckResult]

    @property
    def errors(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "fail" and r.check.severity == "error"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "fail" and r.check.severity == "warn"]


def run_checks(db: Database, as_of: date, checks: list[Check] = CHECKS) -> RunSummary:
    ctx = {"as_of": as_of.isoformat(), "freshness_cutoff": (as_of - timedelta(days=3)).isoformat()}
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = f"{started[:19].replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:6]}"
    results = []
    for check in checks:
        df = db.query_df(check.sql, check.params(ctx))
        results.append(CheckResult(check, len(df), df.head(SAMPLE_ROWS)))
        level = logging.INFO if len(df) == 0 else (logging.ERROR if check.severity == "error" else logging.WARNING)
        log.log(level, "dq: %-36s %s (%d rows)", check.name, "PASS" if len(df) == 0 else "FAIL", len(df))

    summary = RunSummary(run_id, started, results)
    with db.transaction():
        db.execute(
            "INSERT INTO dq_run (run_id, started_at, finished_at, n_checks, n_errors, n_warnings) VALUES (?, ?, ?, ?, ?, ?)",
            [run_id, started, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             len(results), len(summary.errors), len(summary.warnings)],
        )
        db.executemany(
            """INSERT INTO dq_result (run_id, check_name, category, severity, status, failed_rows, sample, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [[run_id, r.check.name, r.check.category, r.check.severity, r.status, r.failed_rows,
              r.sample.to_json(orient="records", force_ascii=False), r.check.description] for r in results],
        )
    return summary


def write_report(summary: RunSummary, reports_dir: Path, extra: dict[str, int] | None = None) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Отчёт о качестве данных",
        "",
        f"Запуск `{summary.run_id}` · {summary.started_at} · "
        f"**ошибок: {len(summary.errors)}**, **предупреждений: {len(summary.warnings)}**, "
        f"проверок: {len(summary.results)}",
        "",
    ]
    if extra:
        lines += ["## Загружено строк", "", "| Таблица | Строк |", "|---|---|"]
        lines += [f"| {t} | {n} |" for t, n in extra.items()]
        lines.append("")
    lines += ["## Проверки", "", "| Статус | Уровень | Измерение | Проверка | Строк-нарушений |", "|---|---|---|---|---|"]
    order = {"error": 0, "warn": 1}
    for r in sorted(summary.results, key=lambda r: (r.status == "pass", order[r.check.severity], r.check.name)):
        icon = "✅" if r.status == "pass" else ("❌" if r.check.severity == "error" else "⚠️")
        lines.append(f"| {icon} | {r.check.severity} | {r.check.category} | `{r.check.name}` | {r.failed_rows} |")
    lines.append("")
    failed = [r for r in summary.results if r.status == "fail"]
    if failed:
        lines += ["## Подробности", ""]
        for r in failed:
            lines += [f"### `{r.check.name}`", "", r.check.description, "",
                      _markdown_table(r.sample), ""]
            if r.failed_rows > len(r.sample):
                lines += [f"_…и ещё строк: {r.failed_rows - len(r.sample)}_", ""]
    text = "\n".join(lines)
    path = reports_dir / "dq_report.md"
    path.write_text(text)
    (reports_dir / f"dq_report_{summary.run_id}.md").write_text(text)
    return path


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "---|" * len(df.columns)
    rows = ["| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


def send_alert(summary: RunSummary, token: str | None, chat_id: str | None) -> bool:
    """Telegram alert when there are errors. Silently skipped if not configured."""
    if not summary.errors or not token or not chat_id:
        return False
    text = "Качество данных: ошибок {}\n{}".format(
        len(summary.errors), "\n".join(f"• {r.check.name}: {r.failed_rows}" for r in summary.errors))
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10).read()
        return True
    except Exception as exc:  # noqa: BLE001 - an alerting failure must not fail the pipeline
        log.warning("telegram alert failed: %s", exc)
        return False


def summary_json(summary: RunSummary) -> str:
    return json.dumps({
        "run_id": summary.run_id,
        "errors": [r.check.name for r in summary.errors],
        "warnings": [r.check.name for r in summary.warnings],
    }, ensure_ascii=False)
