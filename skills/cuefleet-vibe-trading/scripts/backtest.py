#!/usr/bin/env python3
"""Replay event-contract signals against minute futures archive prices.

Decisions are already made by the strategy. An order enters at the next minute
boundary strictly after its decision, using that minute's exact opening price.
Expiry is measured from entry and also uses an exact minute open. An absent
entry is skipped. An entered position with an absent expiry stays unresolved,
occupies its slot until expiry, and contributes no realized PnL. This price
proxy does not reproduce Binance event-contract quotes or settlement.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import heapq
import json
from pathlib import Path
from tempfile import TemporaryDirectory


MINUTE_MS = 60_000
EVENT_CONTRACT_DURATIONS = (10, 30, 60, 1440)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MAX_TIMESTAMP = 253_402_300_799_999
HISTORY_COLUMNS = ("open_time", "open", "high", "low", "close", "volume")
SIGNAL_COLUMNS = ("signal_time", "direction")
TRADE_COLUMNS = (
    "signal_index", "signal_time", "direction", "entry_time", "expiry_time",
    "entry_open", "expiry_open", "status", "reason", "pnl",
)


def csv_rows(path, fields):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream, strict=True)
        header = next(rows, [])
        if len(header) != len(set(header)) or not set(fields).issubset(header):
            raise ValueError(f"{path} requires columns {', '.join(fields)}")
        indices = [header.index(field) for field in fields]
        for values in rows:
            if len(values) != len(header):
                raise ValueError(f"{path} line {rows.line_num} has the wrong column count")
            yield rows.line_num, [values[index] for index in indices]


def timestamp(value, label):
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be UTC Unix milliseconds") from error
    if not 0 <= result <= MAX_TIMESTAMP:
        raise ValueError(f"{label} is outside the supported UTC range")
    return result


def positive_decimal(value, label):
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be a positive decimal") from error
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{label} must be a positive decimal")
    return result


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_signals(path, duration):
    signals = []
    for line, (decision, direction) in csv_rows(path, SIGNAL_COLUMNS):
        decision = timestamp(decision, f"{path} line {line} signal_time")
        direction = direction.strip().upper()
        if direction not in {"LONG", "SHORT"}:
            raise ValueError(f"{path} line {line} direction must be LONG or SHORT")
        entry = (decision // MINUTE_MS + 1) * MINUTE_MS
        signals.append({
            "signal_index": len(signals) + 1,
            "signal_time": decision,
            "direction": direction,
            "entry_time": entry,
            "expiry_time": entry + duration * MINUTE_MS,
        })
    return sorted(signals, key=lambda signal: signal["signal_time"])


def read_opens(path, wanted):
    prices = {}
    first = previous = None
    count = 0
    for line, (opened, price, *_) in csv_rows(path, HISTORY_COLUMNS):
        opened = timestamp(opened, f"{path} line {line} open_time")
        if opened % MINUTE_MS or (previous is not None and opened <= previous):
            raise ValueError(f"{path} line {line} open_time must be an increasing minute boundary")
        price = positive_decimal(price, f"{path} line {line} open")
        if opened in wanted:
            prices[opened] = price
        if first is None:
            first = opened
        previous = opened
        count += 1
    return prices, {"firstOpenTime": first, "lastOpenTime": previous, "rows": count}


def replay(signals, prices, stake, payout_ratio, max_concurrent):
    active = []
    results = []
    for signal in signals:
        entry = signal["entry_time"]
        expiry = signal["expiry_time"]
        while active and active[0] <= entry:
            heapq.heappop(active)
        row = {**signal, "status": "skipped"}
        results.append(row)
        if entry not in prices:
            row["reason"] = "missing_entry_open"
            continue
        if len(active) >= max_concurrent:
            row["reason"] = "max_concurrent"
            continue
        heapq.heappush(active, expiry)
        row["entry_open"] = prices[entry]
        if expiry not in prices:
            row.update(status="unresolved", reason="missing_expiry_open")
            continue
        row["expiry_open"] = prices[expiry]
        if prices[entry] == prices[expiry]:
            row.update(status="tie", pnl=Decimal(0))
        elif (prices[expiry] > prices[entry]) == (signal["direction"] == "LONG"):
            row.update(status="win", pnl=stake * payout_ratio)
        else:
            row.update(status="loss", pnl=-stake)
    return results


def period_rows(values):
    return [{"period": period, "pnl": str(pnl)} for period, pnl in sorted(values.items())]


def summarize(rows):
    counts = Counter(row["status"] for row in rows)
    reasons = Counter(row["reason"] for row in rows if "reason" in row)
    settlements = defaultdict(Decimal)
    for row in rows:
        if "pnl" in row:
            settlements[row["expiry_time"]] += row["pnl"]

    daily, monthly = defaultdict(Decimal), defaultdict(Decimal)
    cumulative = peak = drawdown = Decimal(0)
    for expiry, pnl in sorted(settlements.items()):
        day = (EPOCH + timedelta(milliseconds=expiry)).date().isoformat()
        daily[day] += pnl
        monthly[day[:7]] += pnl
        cumulative += pnl
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)

    settled = counts["win"] + counts["loss"] + counts["tie"]
    return {
        "totals": {
            "signals": len(rows), "positionsOpened": settled + counts["unresolved"],
            "settled": settled, "wins": counts["win"], "losses": counts["loss"],
            "ties": counts["tie"], "skipped": counts["skipped"],
            "unresolved": counts["unresolved"], "realizedPnl": str(cumulative),
            "maxDrawdown": str(drawdown),
        },
        "skippedReasons": dict(sorted(reasons.items())),
        "daily": period_rows(daily),
        "monthly": period_rows(monthly),
    }


def write_chart(daily, monthly, destination):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
    from matplotlib.figure import Figure

    figure = Figure(figsize=(10, 8), layout="constrained", facecolor="white")
    FigureCanvasAgg(figure)
    top, middle, bottom = figure.subplots(3, 1)
    values = [Decimal(item["pnl"]) for item in daily]
    balance = Decimal(0)
    cumulative = []
    for value in values:
        balance += value
        cumulative.append(float(balance))
    days = [datetime.fromisoformat(item["period"]) for item in daily]
    months = [datetime.fromisoformat(item["period"] + "-01") for item in monthly]
    if days:
        top.plot([days[0] - timedelta(days=1), *days], [0, *cumulative], color="#286a56", linewidth=2)
        middle.bar(days, [float(value) for value in values], width=0.8,
                   color=["#297a65" if value >= 0 else "#b64e51" for value in values])
    if months:
        month_values = [float(item["pnl"]) for item in monthly]
        bottom.bar(months, month_values, width=20,
                   color=["#297a65" if value >= 0 else "#b64e51" for value in month_values])
    for axis, title, dates in (
        (top, "Cumulative realized PnL", days),
        (middle, "Daily realized PnL", days),
        (bottom, "Monthly realized PnL", months),
    ):
        axis.set_title(title, loc="left")
        axis.set_ylabel("USDT")
        axis.axhline(0, color="#788783", linewidth=0.8)
        axis.set_axisbelow(True)
        axis.grid(axis="y", alpha=0.25)
        axis.spines[["top", "right"]].set_visible(False)
        if dates:
            locator = AutoDateLocator(minticks=3, maxticks=8)
            axis.xaxis.set_major_locator(locator)
            axis.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        else:
            axis.set_xticks([])
            axis.text(0.5, 0.65, "No settled trades", ha="center", transform=axis.transAxes)
    bottom.set_xlabel("UTC")
    figure.savefig(destination, dpi=160)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--signals", type=Path, required=True)
    parser.add_argument("--price-source", choices=("binance-um-futures", "binance-index", "synthetic"),
                        default="binance-um-futures")
    parser.add_argument("--duration-minutes", type=int, choices=EVENT_CONTRACT_DURATIONS, required=True)
    parser.add_argument("--stake", required=True, help="Fixed stake per trade in USDT")
    parser.add_argument("--payout-ratio", required=True, help="Net profit per unit staked on a win")
    parser.add_argument("--max-concurrent", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-chart", action="store_true", help="Write JSON and CSV only")
    args = parser.parse_args(argv)
    if args.max_concurrent < 1:
        parser.error("maximum concurrency must be a positive integer")
    try:
        stake = positive_decimal(args.stake, "stake")
        payout = positive_decimal(args.payout_ratio, "payout-ratio")
        signals = read_signals(args.signals, args.duration_minutes)
        wanted = {signal[key] for signal in signals for key in ("entry_time", "expiry_time")}
        prices, window = read_opens(args.history, wanted)
        rows = replay(signals, prices, stake, payout, args.max_concurrent)
        summary = {
            "schemaVersion": "cuefleet-backtest-v1",
            "history": {**window, "sha256": sha256(args.history)},
            "signals": {"rows": len(signals), "sha256": sha256(args.signals)},
            "parameters": {
                "durationMinutes": args.duration_minutes, "maxConcurrent": args.max_concurrent,
                "stake": str(stake), "payoutRatio": str(payout),
            },
            "assumptions": {
                "priceSource": args.price_source,
                "entry": "exact_next_minute_open_strictly_after_decision",
                "expiry": "exact_minute_open_at_entry_plus_duration",
                "tie": "stake_refunded",
                "costs": "no_fees_or_slippage",
                "timezone": "UTC",
            },
            **summarize(rows),
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=args.output_dir) as temp:
            folder = Path(temp)
            with (folder / "trades.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=TRADE_COLUMNS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
            if not args.no_chart:
                write_chart(summary["daily"], summary["monthly"], folder / "performance.png")
            for item in sorted(folder.iterdir()):
                item.replace(args.output_dir / item.name)
    except (OSError, ValueError, csv.Error) as error:
        parser.error(str(error))
    except ModuleNotFoundError as error:
        if error.name != "matplotlib":
            raise
        parser.error("Matplotlib is required to draw the report. Install matplotlib or pass --no-chart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
