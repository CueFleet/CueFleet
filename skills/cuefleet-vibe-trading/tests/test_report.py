import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from report import performance_figure, run


class ReportTest(unittest.TestCase):
    def test_chart_axes_share_exact_partial_range_and_partition_boundaries(self):
        from matplotlib.dates import date2num

        def at(month, day, hour):
            return datetime(2025, month, day, hour, tzinfo=timezone.utc)

        edges = (at(1, 31, 12), at(2, 1, 6), at(2, 1, 18), at(2, 2, 12))
        report = {
            "schemaVersion": "cuefleet-quant-report-v1",
            "partitions": {stage: {"start_open_time": int(left.timestamp() * 1000),
                                   "end_open_time_exclusive": int(right.timestamp() * 1000)}
                           for stage, left, right in zip(("train", "validation", "test"), edges, edges[1:])},
            "daily": [{"period": "2025-01-31", "pnl": "5"},
                      {"period": "2025-02-01", "pnl": "-4"},
                      {"period": "2025-02-02", "pnl": "10"}],
            "monthly": [{"period": "2025-01", "pnl": "5"},
                        {"period": "2025-02", "pnl": "6"}],
        }
        figure = performance_figure(report)
        top, middle, bottom = figure.axes
        for axis in figure.axes:
            self.assertEqual(axis.get_xlim(), (date2num(edges[0]), date2num(edges[-1])))
            self.assertEqual([line.get_xdata()[0] for line in axis.lines if (line.get_gid() or "").startswith("split-")],
                             list(edges[1:3]))
        values = list(top.lines[0].get_ydata())
        self.assertEqual(values, [0, 5, 1, 11])
        self.assertEqual(top.lines[0].get_xdata()[[0, -1]].tolist(), [edges[0], edges[-1]])
        self.assertEqual([bar.get_height() for bar in middle.patches], [5, -4, 10])
        self.assertAlmostEqual(middle.patches[0].get_width(), .5 * .82)
        self.assertAlmostEqual(middle.patches[-1].get_width(), .5 * .82)
        self.assertEqual([bar.get_height() for bar in bottom.patches], [5, 6])
        self.assertAlmostEqual(bottom.patches[0].get_width(), .5 * .82)
        self.assertAlmostEqual(bottom.patches[1].get_width(), 1.5 * .82)

    def test_split_boundaries_do_not_leak_settlement_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            start, minute = 1_704_067_200_000, 60_000
            history = directory / "history.csv"
            with history.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("open_time", "open", "high", "low", "close", "volume"))
                for i in range(240):
                    price = 100 + i
                    writer.writerow((start + i * minute, price, price, price, price, 1))

            splits = directory / "splits"
            subprocess.run([sys.executable, str(SCRIPTS / "market_data.py"), "split", "--input", str(history),
                            "--output-dir", str(splits), "--train-percent", "25", "--validation-percent", "25"],
                           capture_output=True, check=True)
            signals = directory / "signals.csv"
            signals.write_text(f"signal_time,direction\n{start + 58 * minute},LONG\n{start + 60 * minute},LONG\n",
                               encoding="utf-8")
            output = directory / "experiment"
            options = argparse.Namespace(split_dir=splits, signals=signals, output_dir=output, symbol="BTCUSDT",
                                         duration_minutes=10, stake="5", payout_ratio="0.8", max_concurrent=1,
                                         strategy_name="fixture", strategy_revision="v1", strategy_file=None,
                                         hypothesis=None, price_source="synthetic")
            run(options)

            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            train, validation, test = (report["partitions"][key] for key in ("train", "validation", "test"))
            self.assertEqual(train["summary"]["totals"]["unresolved"], 1)
            self.assertEqual(train["summary"]["totals"]["settled"], 0)
            self.assertEqual(validation["summary"]["totals"]["wins"], 1)
            self.assertEqual(Decimal(validation["metrics"]["roi"]), Decimal("0.8"))
            self.assertIsNone(test["metrics"]["winRate"])
            self.assertEqual(Decimal(report["daily"][0]["pnl"]), Decimal(4))
            self.assertEqual(Decimal(report["monthly"][0]["pnl"]), Decimal(4))
            bottom = performance_figure(report).axes[-1]
            self.assertEqual(len(bottom.patches), 1)
            self.assertEqual(bottom.patches[0].get_height(), 4)
            self.assertTrue(any("+4.00 USDT" in text.get_text() for text in bottom.texts))
            self.assertTrue((output / "performance.png").read_bytes().startswith(b"\x89PNG"))
            self.assertTrue((output / "report.md").is_file())

            with (splits / "validation.csv").open("a", encoding="utf-8") as stream:
                stream.write("\n")
            options.output_dir = directory / "corrupt-experiment"
            with self.assertRaisesRegex(ValueError, "validation history checksum mismatch"):
                run(options)
            self.assertFalse(options.output_dir.exists())

    def test_train_test_runs_both_cohorts_and_keeps_standard_report_out_of_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            start, minute, train_rows = 1_704_067_200_000, 60_000, 144
            history = directory / "history.csv"
            with history.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("open_time", "open", "high", "low", "close", "volume"))
                for i in range(240):
                    price = 100 + i
                    writer.writerow((start + i * minute, price, price, price, price, 1))
            splits = directory / "splits"
            subprocess.run([sys.executable, str(SCRIPTS / "market_data.py"), "split", "--input", str(history),
                            "--output-dir", str(splits), "--train-percent", "60", "--mode", "train-test"],
                           capture_output=True, check=True)
            signals = directory / "signals.csv"
            signals.write_text("signal_time,direction\n" +
                               "\n".join(f"{start + i * minute},{direction}" for i, direction in
                                         ((2, "LONG"), (train_rows - 2, "LONG"), (train_rows, "LONG"), (175, "SHORT"))) + "\n",
                               encoding="utf-8")
            output = directory / "experiment"
            run(argparse.Namespace(split_dir=splits, signals=signals, output_dir=output, symbol="BTCUSDT",
                                   duration_minutes=10, stake="5", payout_ratio="0.8", max_concurrent=1,
                                   strategy_name="fixture", strategy_revision="v1", strategy_file=None,
                                   hypothesis=None, price_source="synthetic"))
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(set(report["partitions"]), {"train", "test"})
            train, test = (report["partitions"][stage] for stage in ("train", "test"))
            self.assertEqual(train["summary"]["totals"]["unresolved"], 1)
            self.assertEqual((test["summary"]["totals"]["wins"], test["summary"]["totals"]["losses"]), (1, 1))
            self.assertEqual(Decimal(test["summary"]["totals"]["realizedPnl"]), Decimal(-1))
            self.assertEqual(Decimal(report["daily"][0]["pnl"]), Decimal(3))
            boundary = datetime.fromtimestamp((start + train_rows * minute) / 1000, tz=timezone.utc)
            for axis in performance_figure(report).axes:
                lines = [line for line in axis.lines if (line.get_gid() or "").startswith("split-")]
                self.assertEqual([line.get_xdata()[0] for line in lines], [boundary])
            self.assertTrue((output / "performance.png").read_bytes().startswith(b"\x89PNG"))
            standard = (output / "report.md").read_text(encoding="utf-8")
            development = (output / "development-report.md").read_text(encoding="utf-8")
            self.assertIn("| 样本外测试 |", standard)
            self.assertNotIn("| 训练 |", standard)
            self.assertIn("| 训练 |", development)
            self.assertIn("| 样本外测试 |", development)
            self.assertIn("训练 60% / 样本外 40%", development)
            self.assertIn("缺少到期报价 1 条", development)
