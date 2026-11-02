"""End-to-end test: generate deliveries with planted problems, run the pipeline,
and check that the data quality suite catches every planted problem and
raises no false alarms."""

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fdq import pipeline
from fdq.config import ROOT, Settings
from fdq.generate import generate

# Planted issue -> the check that must catch it.
EXPECTED = {
    "duplicate_events": "events_duplicates",
    "events_missing_player": "events_missing_player",
    "xg_out_of_range": "shots_xg_out_of_range",
    "minute_out_of_range": "events_minute_out_of_range",
    "score_mismatch": "score_mismatch_between_providers",
    "match_missing_in_b": "match_missing_in_provider_b",
    "unmatched_player": "unmatched_players",
    "squad_player_never_played": "unmatched_players",
    "gps_missing_for_match": "gps_missing_for_match",
    "gps_distance_anomaly": "gps_distance_anomaly",
    "gps_impossible_speed": "gps_impossible_speed",
    "gps_duplicate": "gps_duplicates",
    "gps_dropout": "gps_dropout",
}
# Planted issues the pipeline must *resolve* (not report): see test_entity_resolution.
RESOLVED = {"name_typo", "jersey_changed", "return_from_injury_load_spike"}


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.settings = Settings(
            db_url=f"sqlite:///{tmp / 'fdq.db'}",
            raw_dir=tmp / "raw",
            reference_dir=ROOT / "reference",
            reports_dir=tmp / "reports",
            telegram_token=None,
            telegram_chat_id=None,
        )
        cls.manifest = generate(cls.settings.raw_dir, seed=7)
        cls.summary = pipeline.run(cls.settings, date.fromisoformat(cls.manifest["as_of"]))
        cls.db = sqlite3.connect(tmp / "fdq.db")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.tmp.cleanup()

    def failed(self) -> dict[str, int]:
        return {r.check.name: r.failed_rows for r in self.summary.results if r.status == "fail"}

    def test_every_planted_issue_is_detected(self):
        failed = self.failed()
        for issue in self.manifest["issues"]:
            if issue["issue"] in RESOLVED:
                continue
            check = EXPECTED[issue["issue"]]
            with self.subTest(issue=issue["issue"]):
                self.assertIn(check, failed, f"{issue} was not detected")

    def test_no_false_alarms(self):
        expected_checks = {EXPECTED[i["issue"]] for i in self.manifest["issues"] if i["issue"] in EXPECTED}
        unexpected = set(self.failed()) - expected_checks
        self.assertEqual(unexpected, set(), f"checks failed without a planted cause: {unexpected}")

    def test_exact_counts(self):
        failed = self.failed()
        self.assertEqual(failed["events_duplicates"], 5)
        self.assertEqual(failed["events_missing_player"], 4)
        n_unmatched = sum(i["issue"] in ("unmatched_player", "squad_player_never_played") for i in self.manifest["issues"])
        self.assertEqual(failed["unmatched_players"], n_unmatched)

    def test_core_is_cleaned(self):
        stg = self.db.execute("SELECT COUNT(*) FROM stg_a_events").fetchone()[0]
        core = self.db.execute("SELECT COUNT(*) FROM fact_event").fetchone()[0]
        self.assertEqual(stg - core, 5, "duplicates must be removed in core")
        invalid = dict(self.db.execute("SELECT invalid_reason, COUNT(*) FROM fact_gps WHERE is_valid = 0 GROUP BY invalid_reason"))
        self.assertEqual(invalid, {"impossible_speed": 1, "dropout": 1})

    def test_entity_resolution(self):
        for issue in self.manifest["issues"]:
            if issue["issue"] in ("name_typo", "jersey_changed"):
                with self.subTest(issue=issue["issue"]):
                    row = self.db.execute("""
                        SELECT mb.player_id, ma.player_id FROM map_player mb
                        JOIN map_player ma ON ma.source = 'A' AND ma.source_key = ?
                        WHERE mb.source = 'B' AND mb.source_key = ?""",
                        [str(issue["player_a_id"]), issue["b_key"]]).fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row[0], row[1], "provider B player must map to the same canonical player")

    def test_rerun_is_idempotent(self):
        before = self.db.execute("SELECT COUNT(*) FROM stg_a_events").fetchone()[0]
        pipeline.run(self.settings, date.fromisoformat(self.manifest["as_of"]))
        after = self.db.execute("SELECT COUNT(*) FROM stg_a_events").fetchone()[0]
        self.assertEqual(before, after)

    def test_load_spike_is_visible(self):
        issue = next(i for i in self.manifest["issues"] if i["issue"] == "return_from_injury_load_spike")
        pid = self.db.execute("SELECT player_id FROM map_player WHERE source = 'A' AND source_key = ?",
                              [str(issue["player_a_id"])]).fetchone()[0]
        peak = self.db.execute("SELECT MAX(acwr_rolling), MAX(acwr_ewma) FROM mart_player_load WHERE player_id = ?",
                               [pid]).fetchone()
        self.assertGreater(peak[0], 1.5)
        self.assertGreater(peak[1], 1.3)

    def test_report_written(self):
        report = (self.settings.reports_dir / "dq_report.md").read_text()
        self.assertIn("score_mismatch_between_providers", report)
        runs = self.db.execute("SELECT COUNT(*) FROM dq_run").fetchone()[0]
        self.assertGreaterEqual(runs, 1)

    def test_manifest_is_complete(self):
        kinds = {i["issue"] for i in json.loads((self.settings.raw_dir / "_manifest.json").read_text())["issues"]}
        self.assertTrue(kinds <= set(EXPECTED) | RESOLVED, kinds - set(EXPECTED) - RESOLVED)


if __name__ == "__main__":
    unittest.main()
