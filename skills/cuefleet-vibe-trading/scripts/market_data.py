"""Download verified Binance USD-M K-lines and make chronological replay splits."""

import argparse
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile


ARCHIVE_ROOT = "https://data.binance.vision/data/futures/um"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
HEADER = ["open_time", "open", "high", "low", "close", "volume"]
INTERVAL_MS = 60_000
ONE_DAY = timedelta(days=1)
MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
GAP_POLICY = "reject_missing_duplicate_or_out_of_order_minutes"
TRAIN_TEST_PERCENTAGES = (60, 70, 80, 90)


class DataError(ValueError):
    """Invalid archive data or an invalid user-supplied CSV."""


class ArchiveUnavailable(DataError):
    """Binance has not published the archive at the expected path."""


def utc_ms(day):
    return calendar.timegm(day.timetuple()) * 1000


def utc_label(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat(timespec="minutes")


def parse_date(value):
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a UTC date in YYYY-MM-DD format") from exc
    if day.isoformat() != value:
        raise argparse.ArgumentTypeError("expected a UTC date in YYYY-MM-DD format")
    return day


def years_before(day, years):
    if years <= 0 or years >= day.year:
        raise DataError("years must be a positive number within the calendar range")
    if day.month == 2 and day.day == 29 and not calendar.isleap(day.year - years):
        return day.replace(year=day.year - years, day=28)
    return day.replace(year=day.year - years)


def next_month(day):
    if day.month == 12:
        return day.replace(year=day.year + 1, month=1, day=1)
    return day.replace(month=day.month + 1, day=1)


def read_public(url, limit):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                body = response.read(limit + 1)
            if len(body) > limit:
                raise DataError(f"archive response exceeds size limit: {url}")
            return body
        except HTTPError as exc:
            if exc.code == 404:
                raise ArchiveUnavailable(f"archive not yet available: {url}") from exc
            if attempt == 2 or exc.code not in (429, 500, 502, 503, 504):
                raise DataError(f"Binance archive request returned HTTP {exc.code}: {url}") from exc
        except (URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise DataError(f"could not retrieve Binance archive: {url} ({exc})") from exc
        time.sleep(attempt + 1)


def verified_archive(symbol, scope, day):
    period = day.strftime("%Y-%m") if scope == "monthly" else day.isoformat()
    name = f"{symbol}-1m-{period}"
    url = f"{ARCHIVE_ROOT}/{scope}/klines/{symbol}/1m/{name}.zip"
    sidecar = read_public(url + ".CHECKSUM", 4096)
    try:
        checksum = sidecar.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise DataError(f"invalid SHA-256 checksum encoding: {url}") from exc
    match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?" + re.escape(name + ".zip"), checksum)
    if match is None:
        raise DataError(f"invalid SHA-256 checksum file: {url}")
    try:
        archive = read_public(url, MAX_ZIP_BYTES)
    except ArchiveUnavailable as exc:
        raise DataError(f"archive is missing even though its checksum exists: {url}") from exc
    if sha256(archive).hexdigest() != match.group(1).lower():
        raise DataError(f"SHA-256 checksum mismatch: {url}")
    return name, archive


def timestamp(value):
    if not value.isascii() or not value.isdecimal() or len(value) > 15:
        raise DataError("invalid UTC millisecond timestamp")
    return int(value)


def normalized_row(row):
    if len(row) != len(HEADER):
        raise DataError("expected six OHLCV columns")
    open_time = timestamp(row[0])
    if open_time % INTERVAL_MS:
        raise DataError("open_time is not on an exact UTC minute")
    if any(len(value) > 64 for value in row[1:]):
        raise DataError("invalid OHLCV number")
    try:
        opened, high, low, closed, volume = values = [Decimal(value) for value in row[1:]]
    except InvalidOperation as exc:
        raise DataError("invalid OHLCV number") from exc
    if not all(value.is_finite() for value in values) or min(opened, high, low, closed) <= 0 or volume < 0:
        raise DataError("prices must be positive and volume nonnegative")
    if high < max(opened, low, closed) or low > min(opened, closed):
        raise DataError("inconsistent OHLC price range")
    return [open_time, *row[1:]]


def check_minute(expected, actual):
    if actual > expected:
        raise DataError(f"missing minute {utc_label(expected)} before {utc_label(actual)}")
    if actual < expected:
        raise DataError(f"duplicate or out-of-order minute {utc_label(actual)}; expected {utc_label(expected)}")


def archive_rows(name, payload, archive_start, archive_end, start, end):
    expected = utc_ms(start)
    lower, upper = utc_ms(archive_start), utc_ms(archive_end)
    start_ms, end_ms = expected, utc_ms(end)
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1 or members[0].filename != f"{name}.csv" or members[0].file_size > MAX_MEMBER_BYTES:
                raise DataError("unexpected CSV member in archive")
            with archive.open(members[0]) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream:
                for line, row in enumerate(csv.reader(stream, strict=True), 1):
                    if line == 1 and row[:len(HEADER)] == HEADER:
                        continue
                    if len(row) != 12:
                        raise DataError(f"row {line}: expected 12 Binance K-line columns")
                    open_time = timestamp(row[0])
                    if not lower <= open_time < upper:
                        raise DataError(f"row {line}: timestamp outside the archive date range")
                    if not start_ms <= open_time < end_ms:
                        continue
                    record = normalized_row(row[:len(HEADER)])
                    if timestamp(row[6]) != open_time + INTERVAL_MS - 1:
                        raise DataError(f"row {line}: invalid 1-minute K-line close_time")
                    check_minute(expected, open_time)
                    expected += INTERVAL_MS
                    yield record
        if expected != end_ms:
            raise DataError(f"missing minute {utc_label(expected)} at the end of the requested range")
    except (BadZipFile, csv.Error, UnicodeDecodeError, DataError) as exc:
        raise DataError(f"{name}: {exc}") from exc


def download_rows(symbol, start, end):
    current = start
    while current < end:
        month = current.replace(day=1)
        month_end = next_month(month)
        stop = min(end, month_end)
        try:
            archive = verified_archive(symbol, "monthly", month)
        except ArchiveUnavailable:
            while current < stop:
                day_end = current + ONE_DAY
                try:
                    daily = verified_archive(symbol, "daily", current)
                except ArchiveUnavailable as exc:
                    raise DataError(f"Binance has no verified daily archive for {current.isoformat()}: {exc}") from exc
                yield from archive_rows(*daily, current, day_end, current, day_end)
                current = day_end
        else:
            yield from archive_rows(*archive, month, month_end, current, stop)
            current = stop


def download(symbol, start, end, output):
    if symbol not in SYMBOLS:
        raise DataError("symbol must be BTCUSDT or ETHUSDT")
    if start >= end or end > datetime.now(timezone.utc).date():
        raise DataError("choose a nonempty UTC range ending no later than today (exclusive)")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cuefleet-download-", dir=output.parent) as temporary:
        pending = Path(temporary) / "dataset.csv"
        with pending.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(HEADER)
            writer.writerows(download_rows(symbol, start, end))
        os.replace(pending, output)
    return {"symbol": symbol, "interval_ms": INTERVAL_MS, "rows": (end - start).days * 1440,
            "start_open_time": utc_ms(start), "end_open_time_exclusive": utc_ms(end),
            "market": "binance_usd_m_futures_contract", "gap_policy": GAP_POLICY}


def dataset_rows(stream, digest):
    def lines():
        for line, raw in enumerate(stream, 1):
            digest.update(raw)
            yield raw.decode("utf-8-sig" if line == 1 else "utf-8")

    try:
        reader = csv.reader(lines(), strict=True)
        if next(reader, None) != HEADER:
            raise DataError("expected CSV header: " + ",".join(HEADER))
        expected = None
        for line, row in enumerate(reader, 2):
            try:
                record = normalized_row(row)
                if expected is not None:
                    check_minute(expected, record[0])
            except DataError as exc:
                raise DataError(f"dataset row {line}: {exc}") from exc
            expected = record[0] + INTERVAL_MS
            yield record
    except (UnicodeDecodeError, csv.Error) as exc:
        raise DataError(f"invalid UTF-8 CSV dataset: {exc}") from exc


def file_sha256(path):
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split(input_path, output_dir, train_percent=60, validation_percent=None, *, mode="train-validation-test"):
    if mode == "train-test":
        if type(train_percent) is not int or train_percent not in TRAIN_TEST_PERCENTAGES or validation_percent is not None:
            raise DataError("train-test supports a train percentage of 60, 70, 80 or 90")
    elif mode == "train-validation-test":
        validation_percent = 20 if validation_percent is None else validation_percent
        if min(train_percent, validation_percent) <= 0 or train_percent + validation_percent >= 100:
            raise DataError("split percentages must leave a positive share for train, validation and test")
    else:
        raise DataError("unsupported chronological split mode")
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise DataError("split output directory must be a new path")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with Path(input_path).open("rb") as source:
        digest = sha256()
        records = dataset_rows(source, digest)
        first = next(records, None)
        count = 0 if first is None else 1 + sum(1 for _ in records)
        train_end = count * train_percent // 100
        if mode == "train-test":
            if not 0 < train_end < count:
                raise DataError("dataset is too small for two nonempty chronological splits")
            ranges = (("train", 0, train_end), ("test", train_end, count))
        else:
            validation_end = count * (train_percent + validation_percent) // 100
            if not 0 < train_end < validation_end < count:
                raise DataError("dataset is too small for three nonempty chronological splits")
            ranges = (("train", 0, train_end), ("validation", train_end, validation_end),
                      ("test", validation_end, count))
        manifest = {"version": 1, "dataset_sha256": digest.hexdigest(), "dataset_rows": count,
                    "interval_ms": INTERVAL_MS, "gap_policy": GAP_POLICY, "time_zone": "UTC",
                    "partitions": {}}
        if mode == "train-test":
            manifest.update(split_mode=mode, train_percent=train_percent)
        source.seek(0)
        check_digest = sha256()
        records = dataset_rows(source, check_digest)
        with tempfile.TemporaryDirectory(prefix=".cuefleet-split-", dir=output_dir.parent) as temporary:
            staging = Path(temporary) / "split"
            staging.mkdir()
            for name, start, end in ranges:
                part = staging / f"{name}.csv"
                with part.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream, lineterminator="\n")
                    writer.writerow(HEADER)
                    for _ in range(start, end):
                        row = next(records, None)
                        if row is None:
                            raise DataError("dataset changed during split")
                        writer.writerow(row)
                manifest["partitions"][name] = {"file": part.name, "rows": end - start,
                    "start_open_time": first[0] + start * INTERVAL_MS,
                    "end_open_time_exclusive": first[0] + end * INTERVAL_MS, "sha256": file_sha256(part)}
            if next(records, None) is not None or check_digest.hexdigest() != manifest["dataset_sha256"]:
                raise DataError("dataset changed during split")
            (staging / "split-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                                        encoding="utf-8", newline="\n")
            staging.rename(output_dir)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    download_parser = commands.add_parser("download", help="download verified 1-minute USD-M contract OHLCV")
    download_parser.add_argument("--symbol", choices=SYMBOLS, required=True)
    download_parser.add_argument("--end", type=parse_date, help="exclusive UTC date, defaults to today")
    start_group = download_parser.add_mutually_exclusive_group()
    start_group.add_argument("--start", type=parse_date, help="inclusive UTC date")
    start_group.add_argument("--years", type=int, default=5, help="calendar years ending at --end, defaults to 5")
    download_parser.add_argument("--output", required=True, type=Path)
    split_parser = commands.add_parser("split", help="create non-overlapping chronological CSV datasets")
    split_parser.add_argument("--input", required=True, type=Path)
    split_parser.add_argument("--output-dir", required=True, type=Path, help="a new directory for CSVs and manifest")
    split_parser.add_argument("--mode", choices=("train-validation-test", "train-test"), default="train-validation-test")
    split_parser.add_argument("--train-percent", type=int, default=60)
    split_parser.add_argument("--validation-percent", type=int, help="defaults to 20 in train-validation-test mode")
    options = parser.parse_args(argv)
    try:
        if options.command == "download":
            end = options.end or datetime.now(timezone.utc).date()
            start = options.start or years_before(end, options.years)
            result = download(options.symbol, start, end, options.output)
        else:
            result = split(options.input, options.output_dir, options.train_percent, options.validation_percent,
                           mode=options.mode)
    except (DataError, OSError) as exc:
        parser.exit(1, f"market data: {exc}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
