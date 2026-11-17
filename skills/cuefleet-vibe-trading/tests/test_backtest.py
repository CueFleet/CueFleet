import csv
from contextlib import redirect_stderr
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backtest


class BacktestTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.history = self.root / "history.csv"
        self.signals = self.root / "signals.csv"
        self.output = self.root / "output"
        self.start = int(datetime(2025, 1, 31, 23, 48, tzinfo=timezone.utc).timestamp()) * 1000

    def minute(self, offset):
        return self.start + offset * backtest.MINUTE_MS

    def record(self, prices, signals):
        with self.history.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows([
                backtest.HISTORY_COLUMNS,
                *[(self.minute(minute), price, price, price, price, 0) for minute, price in prices],
            ])
        with self.signals.open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerows([backtest.SIGNAL_COLUMNS, *signals])

    def run_replay(self, duration=10, chart=False):
        args = [
            "--history", str(self.history), "--signals", str(self.signals),
            "--duration-minutes", str(duration), "--stake", "100", "--payout-ratio", "0.8",
            "--max-concurrent", "1", "--output-dir", str(self.output),
        ]
        self.assertEqual(backtest.main(args if chart else args + ["--no-chart"]), 0)
        summary = json.loads((self.output / "summary.json").read_text(encoding="utf-8"))
        with (self.output / "trades.csv").open(encoding="utf-8", newline="") as stream:
            return summary, list(csv.DictReader(stream))

    def test_exact_opens_realized_utc_and_missing_prices(self):
        self.record(
            [(0, 120), (1, 100), (11, 105), (21, 95), (41, 110), (51, 110), (61, 105)],
            [(self.minute(10), "LONG"), (self.minute(0), "LONG"), (self.minute(20), "SHORT"),
             (self.minute(30) + 900, "LONG"), (self.minute(40), "SHORT"),
             (self.minute(40), "SHORT"), (self.minute(50), "SHORT")],
        )
        summary, rows = self.run_replay()
        self.assertEqual(summary["schemaVersion"], "cuefleet-backtest-v1")
        self.assertEqual(summary["history"], {
            "firstOpenTime": self.minute(0), "lastOpenTime": self.minute(61), "rows": 7,
            "sha256": hashlib.sha256(self.history.read_bytes()).hexdigest(),
        })
        self.assertEqual(summary["signals"]["sha256"], hashlib.sha256(self.signals.read_bytes()).hexdigest())
        self.assertEqual(summary["totals"], {
            "signals": 7, "positionsOpened": 5, "settled": 4, "wins": 2,
            "losses": 1, "ties": 1, "skipped": 2, "unresolved": 1,
            "realizedPnl": "60.0", "maxDrawdown": "100.0",
        })
        self.assertEqual([row["status"] for row in rows], ["win", "loss", "unresolved", "skipped", "tie", "skipped", "win"])
        self.assertEqual([row["reason"] for row in rows if row["reason"]], ["missing_expiry_open", "missing_entry_open", "max_concurrent"])
        self.assertEqual([row["signal_index"] for row in rows], ["2", "1", "3", "4", "5", "6", "7"])
        self.assertEqual(rows[0]["entry_open"], "100")
        self.assertEqual(rows[0]["expiry_open"], "105")
        self.assertEqual(rows[2]["pnl"], "")
        self.assertEqual(rows[3]["entry_time"], str(self.minute(31)))
        self.assertEqual(summary["daily"], [{"period": "2025-01-31", "pnl": "80.0"}, {"period": "2025-02-01", "pnl": "-20.0"}])
        self.assertEqual(summary["monthly"], [{"period": "2025-01", "pnl": "80.0"}, {"period": "2025-02", "pnl": "-20.0"}])

    def test_unresolved_position_consumes_capacity_until_expiry(self):
        self.record(
            [(1, 100), (2, 101), (12, 102), (22, 103)],
            [(self.minute(minute), "LONG") for minute in [0, 1, 11]],
        )
        _, rows = self.run_replay()
        self.assertEqual([row["status"] for row in rows], ["unresolved", "skipped", "win"])
        self.assertEqual(rows[1]["reason"], "max_concurrent")

    def test_empty_signals_with_no_chart(self):
        self.record([(0, 100)], [])
        summary, rows = self.run_replay()
        self.assertEqual(rows, [])
        self.assertEqual(summary["totals"]["settled"], 0)
        self.assertEqual(summary["totals"]["maxDrawdown"], "0")
        self.assertEqual(summary["daily"], [])
        self.assertFalse((self.output / "performance.png").exists())

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "matplotlib not installed")
    def test_default_performance_png(self):
        self.record([(1, 100), (11, 110)], [(self.minute(0), "LONG")])
        self.run_replay(chart=True)
        png = (self.output / "performance.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertGreater(len(png), 1000)

    def test_cli_accepts_only_exchange_durations(self):
        self.record([(0, 100)], [])
        for duration in (10, 30, 60, 1440):
            with self.subTest(duration=duration):
                summary, _ = self.run_replay(duration=duration)
                self.assertEqual(summary["parameters"]["durationMinutes"], duration)
        for duration in (0, 5, 120):
            with self.subTest(duration=duration), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.run_replay(duration=duration)
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
