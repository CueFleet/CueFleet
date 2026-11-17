import csv
from datetime import date
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import market_data as data


JAN_1 = date(2024, 1, 1)
JAN_2 = date(2024, 1, 2)
JAN_3 = date(2024, 1, 3)


def dataset_row(open_time):
    return [open_time, "12.00", "13.50", "11.90", "12.50", "15.0"]


def archive_bytes(name, start=JAN_1, *, header=True, missing=None):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    if header:
        writer.writerow(data.HEADER + ["close_time", "quote_volume", "count", "taker_buy_volume",
                                      "taker_buy_quote_volume", "ignore"])
    for minute in range(1440):
        if minute == missing:
            continue
        open_time = data.utc_ms(start) + minute * data.INTERVAL_MS
        writer.writerow(dataset_row(open_time) + [open_time + data.INTERVAL_MS - 1, 0, 0, 0, 0, 0])
    payload = io.BytesIO()
    with ZipFile(payload, "w") as archive:
        archive.writestr(name + ".csv", stream.getvalue())
    return payload.getvalue()


class MarketDataTest(unittest.TestCase):
    def test_calendar_start_handles_leap_dates(self):
        self.assertEqual(data.years_before(date(2024, 2, 29), 5), date(2019, 2, 28))
        self.assertEqual(data.years_before(JAN_1, 5), date(2019, 1, 1))

    def test_download_accepts_headerless_monthly_archive_and_trims_to_requested_day(self):
        name = "BTCUSDT-1m-2024-01"
        archive = archive_bytes(name, JAN_2, header=False)
        checksum = f"{sha256(archive).hexdigest()}  {name}.zip\n".encode("ascii")
        with tempfile.TemporaryDirectory() as temporary, patch.object(data, "read_public", side_effect=[checksum, archive]) as fetch:
            output = Path(temporary) / "BTCUSDT.csv"
            result = data.download("BTCUSDT", JAN_2, JAN_3, output)
            self.assertEqual(result["rows"], 1440)
            self.assertIn("/um/monthly/klines/BTCUSDT/1m/", fetch.call_args_list[0].args[0])
            with output.open(newline="", encoding="utf-8") as stream:
                records = list(csv.reader(stream))
            self.assertEqual(records[0], data.HEADER)
            self.assertEqual(records[1], [str(v) for v in dataset_row(data.utc_ms(JAN_2))])
            self.assertEqual(int(records[-1][0]), data.utc_ms(JAN_3) - data.INTERVAL_MS)

    def test_missing_monthly_checksum_falls_back_to_verified_daily_archives(self):
        payloads = []
        for day in (JAN_1, JAN_2):
            name = f"ETHUSDT-1m-{day}"
            payload = archive_bytes(name, day)
            payloads.extend([f"{sha256(payload).hexdigest()} *{name}.zip\n".encode("ascii"), payload])
        with tempfile.TemporaryDirectory() as temporary, patch.object(data, "read_public", side_effect=[data.ArchiveUnavailable(), *payloads]) as fetch:
            output = Path(temporary) / "ETHUSDT.csv"
            result = data.download("ETHUSDT", JAN_1, JAN_3, output)
            self.assertEqual(result["rows"], 2880)
            self.assertIn("/daily/", fetch.call_args_list[1].args[0])
            self.assertIn("2024-01-02.zip", fetch.call_args_list[4].args[0])
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 2881)

    def test_bad_digest_preserves_existing_output_and_does_not_fall_back(self):
        sidecar = f"{'0' * 64}  BTCUSDT-1m-2024-01.zip\n".encode("ascii")
        with tempfile.TemporaryDirectory() as temporary, patch.object(data, "read_public", side_effect=[sidecar, b"wrong archive"]) as fetch:
            output = Path(temporary) / "BTCUSDT.csv"
            output.write_bytes(b"prior complete data")
            with self.assertRaisesRegex(data.DataError, "checksum mismatch"):
                data.download("BTCUSDT", JAN_1, JAN_2, output)
            self.assertEqual(output.read_bytes(), b"prior complete data")
            self.assertEqual(fetch.call_count, 2)

    def test_archive_gap_rejects_entire_output(self):
        name = "BTCUSDT-1m-2024-01"
        archive = archive_bytes(name, missing=42)
        with tempfile.TemporaryDirectory() as temporary, patch.object(data, "verified_archive", return_value=(name, archive)):
            output = Path(temporary) / "BTCUSDT.csv"
            with self.assertRaisesRegex(data.DataError, "missing minute 2024-01-01T00:42"):
                data.download("BTCUSDT", JAN_1, JAN_2, output)
            self.assertFalse(output.exists())

    def write_input(self, path, minutes):
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(data.HEADER)
            writer.writerows(dataset_row(data.utc_ms(JAN_1) + n * data.INTERVAL_MS) for n in minutes)

    def test_split_uses_nonoverlapping_deterministic_half_open_intervals(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original = folder / "input.csv"
            self.write_input(original, range(11))
            start = data.utc_ms(JAN_1)
            cutoff = [start + n * data.INTERVAL_MS for n in (0, 6, 8, 11)]
            result = data.split(original, folder / "output")
            self.assertEqual(result["dataset_rows"], 11)
            self.assertEqual(result["dataset_sha256"], sha256(original.read_bytes()).hexdigest())
            combined = []
            for name, count, start, stop in zip(("train", "validation", "test"), (6, 2, 3), cutoff, cutoff[1:]):
                part = result["partitions"][name]
                self.assertEqual((part["rows"], part["start_open_time"], part["end_open_time_exclusive"]), (count, start, stop))
                path = folder / "output" / part["file"]
                self.assertEqual(sha256(path.read_bytes()).hexdigest(), part["sha256"])
                combined.extend(path.read_bytes().splitlines(keepends=True)[1:])
            self.assertEqual(combined, original.read_bytes().splitlines(keepends=True)[1:])
            data.split(original, folder / "second")
            self.assertEqual((folder / "output" / "split-manifest.json").read_bytes(),
                             (folder / "second" / "split-manifest.json").read_bytes())
            self.assertEqual(json.loads((folder / "output" / "split-manifest.json").read_bytes()), result)

    def test_invalid_minute_sequence_and_small_datasets_produce_no_partitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original = folder / "input.csv"
            for minutes, expected in (([0, 1, 3], "missing minute"), ([0, 1, 1], "duplicate"),
                                      ([0, 1, 0], "out-of-order"), ([0, 1], "too small")):
                with self.subTest(minutes=minutes):
                    self.write_input(original, minutes)
                    with self.assertRaisesRegex(data.DataError, expected):
                        data.split(original, folder / "output")
                    self.assertFalse((folder / "output").exists())

    def test_train_test_percentages_freeze_exact_half_open_cutoffs(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            original = folder / "input.csv"
            self.write_input(original, range(11))
            start = data.utc_ms(JAN_1)
            for percent, rows in ((60, 6), (70, 7), (80, 8), (90, 9)):
                with self.subTest(percent=percent):
                    manifest = data.split(original, folder / str(percent), train_percent=percent, mode="train-test")
                    self.assertEqual((manifest["split_mode"], manifest["train_percent"]), ("train-test", percent))
                    self.assertEqual(set(manifest["partitions"]), {"train", "test"})
                    train, test = (manifest["partitions"][stage] for stage in ("train", "test"))
                    cutoff = start + rows * data.INTERVAL_MS
                    self.assertEqual((train["rows"], test["rows"]), (rows, 11 - rows))
                    self.assertEqual(train["end_open_time_exclusive"], cutoff)
                    self.assertEqual(test["start_open_time"], cutoff)
            with self.assertRaisesRegex(data.DataError, "60, 70, 80 or 90"):
                data.split(original, folder / "bad", train_percent=65, mode="train-test")
            self.assertFalse((folder / "bad").exists())


if __name__ == "__main__":
    unittest.main()
