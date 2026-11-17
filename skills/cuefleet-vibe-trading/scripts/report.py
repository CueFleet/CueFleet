#!/usr/bin/env python3
"""Run the same replay assumptions on chronological splits and publish one report."""

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from backtest import EVENT_CONTRACT_DURATIONS
from market_data import TRAIN_TEST_PERCENTAGES


STAGES = ("train", "validation", "test")
TRAIN_TEST = ("train", "test")
LABELS = {"train": "训练", "validation": "验证", "test": "样本外测试"}
SIGNAL_COLUMNS = ("signal_time", "direction")
PRICE_SOURCES = {
    "binance-um-futures": "Binance USDⓈ-M 永续合约成交 K 线（代理价）",
    "binance-index": "Binance 指数 K 线",
    "synthetic": "合成数据（演示）",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def moment(milliseconds):
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=milliseconds)


def partition_stages(partitions):
    if set(partitions) == set(TRAIN_TEST):
        return TRAIN_TEST
    if set(partitions) == set(STAGES):
        return STAGES
    raise ValueError("expected either train/test or train/validation/test partitions")


def load_partitions(directory):
    manifest = json.loads((directory / "split-manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1 or manifest["interval_ms"] != 60_000 or manifest["time_zone"] != "UTC":
        raise ValueError("expected a v1 UTC 1-minute split manifest")
    stages = partition_stages(manifest["partitions"])
    parts = [manifest["partitions"][stage] for stage in stages]
    for stage, part in zip(stages, parts):
        start, end, rows = (part[key] for key in ("start_open_time", "end_open_time_exclusive", "rows"))
        if part["file"] != stage + ".csv" or rows <= 0 or end - start != rows * 60_000:
            raise ValueError(f"invalid {stage} range")
        if digest(directory / part["file"]) != part["sha256"]:
            raise ValueError(f"{stage} history checksum mismatch")
    if any(a["end_open_time_exclusive"] != b["start_open_time"] for a, b in zip(parts, parts[1:])):
        raise ValueError("dataset splits must be adjacent and non-overlapping")
    if sum(part["rows"] for part in parts) != manifest["dataset_rows"]:
        raise ValueError("dataset row count does not match partitions")
    if stages == TRAIN_TEST:
        train_percent = manifest.get("train_percent")
        if (manifest.get("split_mode") != "train-test" or type(train_percent) is not int or
                train_percent not in TRAIN_TEST_PERCENTAGES or parts[0]["rows"] != manifest["dataset_rows"] * train_percent // 100):
            raise ValueError("train/test partitions do not match the stated percentage")
    return manifest, parts


def distribute_signals(source, paths, parts):
    with ExitStack() as stack:
        reader = csv.DictReader(stack.enter_context(source.open(encoding="utf-8-sig", newline="")))
        if reader.fieldnames != list(SIGNAL_COLUMNS):
            raise ValueError("expected signal_time,direction header")
        writers = [csv.writer(stack.enter_context(path.open("w", encoding="utf-8", newline=""))) for path in paths]
        for writer in writers:
            writer.writerow(SIGNAL_COLUMNS)
        index, prior = 0, None
        for row in reader:
            raw_time = row["signal_time"] or ""
            if None in row or not raw_time.isascii() or not raw_time.isdecimal():
                raise ValueError(f"invalid signal at line {reader.line_num}")
            decision_time = int(raw_time)
            if prior is not None and decision_time < prior:
                raise ValueError(f"out-of-order signal at line {reader.line_num}")
            while index < len(parts) and decision_time >= parts[index]["end_open_time_exclusive"]:
                index += 1
            if index == len(parts) or decision_time < parts[index]["start_open_time"]:
                raise ValueError(f"signal outside the experiment at line {reader.line_num}")
            writers[index].writerow((decision_time, row["direction"]))
            prior = decision_time


def combined_periods(summaries, parts):
    amounts = {}
    for summary in summaries:
        for item in summary["daily"]:
            day = date.fromisoformat(item["period"])
            amounts[day] = amounts.get(day, Decimal(0)) + Decimal(item["pnl"])
    day = moment(parts[0]["start_open_time"]).date()
    last = moment(parts[-1]["end_open_time_exclusive"] - 1).date()
    daily, months = [], {}
    while day <= last:
        value = amounts.get(day, Decimal(0))
        month = day.isoformat()[:7]
        daily.append({"period": day.isoformat(), "pnl": str(value)})
        months[month] = months.get(month, Decimal(0)) + value
        day += timedelta(days=1)
    return daily, [{"period": month, "pnl": str(value)} for month, value in months.items()]


def calendar_bars(rows, start, end, monthly=False):
    bars = []
    for row in rows:
        period = row["period"] + "-01" if monthly else row["period"]
        opened = datetime.fromisoformat(period).replace(tzinfo=timezone.utc)
        if monthly:
            closed = opened.replace(year=opened.year + (opened.month == 12), month=opened.month % 12 + 1)
        else:
            closed = opened + timedelta(days=1)
        left, right = max(start, opened), min(end, closed)
        if left < right:
            bars.append((left, right, Decimal(row["pnl"])))
    return bars


def performance_figure(report):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties, findfont

    if report["schemaVersion"] != "cuefleet-quant-report-v1":
        raise ValueError("expected a v1 CueFleet quant report")
    stages = partition_stages(report["partitions"])
    ranges = [(moment(report["partitions"][stage]["start_open_time"]),
               moment(report["partitions"][stage]["end_open_time_exclusive"])) for stage in stages]
    if any(left >= right for left, right in ranges) or any(a[1] != b[0] for a, b in zip(ranges, ranges[1:])):
        raise ValueError("expected chronological, adjacent chart partitions")
    start, end = ranges[0][0], ranges[-1][1]
    daily = calendar_bars(report["daily"], start, end)
    monthly = calendar_bars(report["monthly"], start, end, monthly=True)

    font = None
    for family in ("Microsoft YaHei", "Noto Sans CJK SC", "Noto Sans SC"):
        try:
            font = FontProperties(fname=findfont(FontProperties(family=family), fallback_to_default=False))
            break
        except ValueError:
            continue
    if font:
        labels = {"train": "训练", "validation": "验证", "test": "样本外"}
        titles = ("累计 PnL", "日收益", "月收益")
    else:
        labels = {"train": "Train", "validation": "Validation", "test": "Out of sample"}
        titles = ("Cumulative PnL", "Daily PnL", "Monthly PnL")
    stage_labels = tuple(labels[stage] for stage in stages)

    figure = Figure(figsize=(11, 8.2), facecolor="#10161b")
    FigureCanvasAgg(figure)
    axes = figure.subplots(3, 1, sharex=True, gridspec_kw={"height_ratios": (1.2, 1, 1)})
    figure.subplots_adjust(left=.10, right=.974, top=.93, bottom=.10, hspace=.41)
    top, middle, bottom = axes

    closes, balances = [start], [0]
    balance = Decimal(0)
    for _, closed, value in daily:
        balance += value
        closes.append(closed)
        balances.append(float(balance))
    if closes[-1] < end:
        closes.append(end)
        balances.append(float(balance))
    top.step(closes, balances, where="post", color="#92dfbf", linewidth=1.9, zorder=3)

    for axis, bars in ((middle, daily), (bottom, monthly)):
        if bars:
            values = [value for _, _, value in bars]
            axis.bar([left + (right - left) / 2 for left, right, _ in bars],
                     [float(value) for value in values],
                     width=[(right - left) * .82 for left, right, _ in bars],
                     color=["#75c7a7" if value >= 0 else "#d48491" for value in values], alpha=.85, zorder=2)

    for axis, title in zip(axes, titles):
        axis.set_facecolor("#151e24")
        axis.set_title(title, loc="left", pad=9, fontproperties=font, color="#e8eef1", fontsize=13)
        axis.set_ylabel("USDT", color="#96a8b2", fontsize=9)
        axis.tick_params(axis="both", colors="#aebbc3", labelsize=9, length=3, pad=6)
        axis.spines[["top", "right"]].set_visible(False)
        axis.spines[["left", "bottom"]].set_color("#35434c")
        axis.set_axisbelow(True)
        axis.grid(axis="y", color="#32414a", alpha=.6, linewidth=.6)
        axis.axhline(0, color="#74878e", linewidth=.7, zorder=1)
        axis.margins(y=.18)
        for stage, (boundary, _) in zip(stages[1:], ranges[1:]):
            axis.axvline(boundary, color="#afbdc6", linestyle=(0, (4, 4)), linewidth=.9, zorder=4,
                        gid=f"split-{stage}")

    if all((right - left) / (end - start) >= .12 for left, right in ranges):
        for label, (left, right) in zip(stage_labels, ranges):
            top.text(left + (right - left) / 2, .965, label, ha="center", va="top", fontsize=9,
                     color="#c1ced5", fontproperties=font, transform=top.get_xaxis_transform())
    else:
        top.text(.99, 1.035, "  /  ".join(stage_labels), ha="right", va="bottom", fontsize=9,
                 color="#c1ced5", fontproperties=font, transform=top.transAxes)
    if len(monthly) == 1:
        period = report["monthly"][0]["period"]
        bottom.text(.98, .94, f"{period}   {monthly[0][2]:+,.2f} USDT", ha="right", va="top", fontsize=9,
                    color="#e8eef1", transform=bottom.transAxes,
                    bbox={"facecolor": "#151e24", "edgecolor": "none", "pad": 3})
    locator = AutoDateLocator(minticks=4, maxticks=8, tz=timezone.utc)
    bottom.xaxis.set_major_locator(locator)
    bottom.xaxis.set_major_formatter(ConciseDateFormatter(locator, tz=timezone.utc))
    bottom.xaxis.get_offset_text().set_color("#aebbc3")
    bottom.set_xlabel("UTC", color="#aebbc3", fontsize=9)
    top.set_xlim(start, end)
    return figure


def render_chart(report, destination):
    performance_figure(report).savefig(destination, dpi=150)


def derived_metrics(part, summary):
    totals = summary["totals"]
    pnl = Decimal(totals["realizedPnl"])
    settled = totals["settled"]
    settled_stake = Decimal(summary["parameters"]["stake"]) * settled
    return {
        "winRate": str(Decimal(totals["wins"]) / settled) if settled else None,
        "roi": str(pnl / settled_stake) if settled_stake else None,
        "dailyPnl": str(pnl * 1440 / part["rows"]),
    }


def write_markdown(destination, report, *, development=False):
    assumptions = report["assumptions"]
    stages = partition_stages(report["partitions"])
    train_test = stages == TRAIN_TEST
    table_stages = ("test",) if train_test and not development else stages
    default_hypothesis = ("按相同执行假设评估样本外表现。" if train_test
                          else "按相同执行假设比较训练、验证和样本外表现。")
    first = moment(report["partitions"]["train"]["start_open_time"]).strftime("%Y-%m-%d %H:%M")
    last = moment(report["partitions"]["test"]["end_open_time_exclusive"]).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# CueFleet 量化实验开发报告" if development else "# CueFleet 量化实验报告", "",
        f"- 策略 **{report['strategy']['name']}** · 版本 `{report['strategy']['revision']}`",
        f"- 标的 **{report['symbol']}** · {report['priceSource']} · 1 分钟 · UTC",
        f"- 数据范围 **{first} → {last} UTC**，含起点、不含终点。",
        f"- 持有 **{assumptions['durationMinutes']} 分钟**，每笔投入 **{assumptions['stake']} USDT**，"
        f"盈利支付率 **{Decimal(assumptions['payoutRatio']):.2%}**，最多同时持仓 **{assumptions['maxConcurrent']} 笔**。",
        "- 信号之后的下一分钟开盘入场，到期分钟开盘结算。各分段独立运行，跨段持仓不转入下一段。缺少到期报价的持仓标为未结算。",
        "- 结果使用固定支付率和分钟级报价近似，不含手续费、滑点或实盘成交延迟。", "",
        "## 实验目标", "", report["strategy"]["hypothesis"] or default_hypothesis, "",
        "## 样本外指标" if table_stages == ("test",) else "## 分段结果", "",
        "区间为 UTC，含起点、不含终点。胜率以全部已结算笔数为分母，含走平。ROI 按已结算盈亏除以已结算投入计算。日均盈亏按分段覆盖的分钟数折算。盈亏及回撤单位为 USDT。", "",
        "| 分段 | 区间（UTC） | 信号 | 已结算（赢/输/平） | 胜率 | ROI | 已结算盈亏 | 日均盈亏 | 最大回撤 | 跳过 / 未结算 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for stage in table_stages:
        label = LABELS[stage]
        part = report["partitions"][stage]
        totals = part["summary"]["totals"]
        metrics = part["metrics"]
        start = moment(part["start_open_time"]).strftime("%Y-%m-%d %H:%M")
        end = moment(part["end_open_time_exclusive"]).strftime("%Y-%m-%d %H:%M")
        rate = f"{Decimal(metrics['winRate']):.1%}" if metrics["winRate"] is not None else "—"
        roi = f"{Decimal(metrics['roi']):.1%}" if metrics["roi"] is not None else "—"
        pnl = Decimal(totals["realizedPnl"])
        daily = Decimal(metrics["dailyPnl"])
        lines.append(f"| {label} | {start} → {end} | {totals['signals']} | {totals['settled']} "
                     f"({totals['wins']}/{totals['losses']}/{totals['ties']}) | {rate} | {roi} | {pnl:+.2f} | "
                     f"{daily:+.2f} | {Decimal(totals['maxDrawdown']):.2f} | {totals['skipped']} / {totals['unresolved']} |")
    test = report["partitions"]["test"]["summary"]["totals"]
    if test["settled"]:
        conclusion = (f"样本外共结算 {test['settled']} 笔，已结算盈亏 {Decimal(test['realizedPnl']):+.2f} USDT，"
                      f"最大回撤 {Decimal(test['maxDrawdown']):.2f} USDT。")
    elif test["signals"]:
        conclusion = (f"样本外有 {test['signals']} 条信号，{test['skipped']} 条跳过，"
                      f"{test['unresolved']} 笔未结算。此次实验没有可评估的样本外交易结果。")
    else:
        conclusion = "样本外没有触发交易信号，此次实验没有可评估的样本外交易结果。"
    if development:
        manifest = report["dataset"]
        train_percent = manifest["train_percent"]
        lines.extend(["", "## 实验配置与诊断", "",
                      f"- 切分比例 **训练 {train_percent}% / 样本外 {100 - train_percent}%**。",
                      f"- 分钟数据 **{manifest['dataset_rows']} 根** · SHA-256 `{manifest['dataset_sha256']}`。",
                      f"- 信号数据 SHA-256 `{report['signalInputSha256']}`。"])
        if report["strategy"]["fileSha256"]:
            lines.append(f"- 策略文件 SHA-256 `{report['strategy']['fileSha256']}`。")
        reason_labels = {"max_concurrent": "在途上限", "missing_entry_open": "缺少入场报价",
                         "missing_expiry_open": "缺少到期报价"}
        for stage in stages:
            part = report["partitions"][stage]
            reasons = "、".join(f"{reason_labels.get(reason, reason)} {count} 条"
                               for reason, count in part["summary"]["skippedReasons"].items()) or "无"
            lines.append(f"- {LABELS[stage]} **{part['rows']} 根** · 跳过和未结算原因 {reasons}。")
    chart_note = ("三联图共用完整数据范围。竖虚线标记样本外测试的起点，累计 PnL 按 UTC 结算日逐日更新。" if train_test else
                  "三联图共用完整数据范围。两条竖虚线分别标记验证和样本外测试的起点，累计 PnL 按 UTC 结算日逐日更新。")
    trade_links = " · ".join(f"[{LABELS[stage] if stage != 'test' else '样本外'}]({stage}/trades.csv)"
                             for stage in table_stages)
    lines.extend([
        "", "## 样本外结果", "", conclusion, "",
        "## 累计 PnL、日收益与月收益", "",
        chart_note, "",
        "![累计 PnL、日收益、月收益](performance.png)", "",
        "## 复现材料", "",
        "[机器可读总报告](report.json)记录输入校验和、回测参数、跳单原因和逐期盈亏。[数据切分清单](split-manifest.json)记录各分段边界。", "",
        f"逐笔记录 {trade_links}", "",
    ])
    destination.write_text("\n".join(lines), encoding="utf-8")


def run(options):
    manifest, parts = load_partitions(options.split_dir)
    stages = partition_stages(manifest["partitions"])
    output = options.output_dir.absolute()
    if output.exists():
        raise ValueError("output directory already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cuefleet-experiment-", dir=output.parent) as temporary:
        scratch = Path(temporary)
        signal_inputs = [scratch / (stage + "-signals.csv") for stage in stages]
        input_hash = digest(options.signals)
        distribute_signals(options.signals, signal_inputs, parts)
        if digest(options.signals) != input_hash:
            raise ValueError("signal file changed during the experiment")
        result = scratch / "report"
        result.mkdir()
        summaries = []
        for stage, part, signals in zip(stages, parts, signal_inputs):
            target = result / stage
            subprocess.run([sys.executable, str(Path(__file__).with_name("backtest.py")),
                            "--history", str(options.split_dir / part["file"]), "--signals", str(signals),
                            "--price-source", options.price_source,
                            "--duration-minutes", str(options.duration_minutes), "--stake", options.stake,
                            "--payout-ratio", options.payout_ratio, "--max-concurrent", str(options.max_concurrent),
                            "--output-dir", str(target), "--no-chart"], check=True)
            summary = json.loads((target / "summary.json").read_text(encoding="utf-8"))
            history = summary["history"]
            expected = (part["sha256"], part["rows"], part["start_open_time"], part["end_open_time_exclusive"] - 60_000)
            actual = (history["sha256"], history["rows"], history["firstOpenTime"], history["lastOpenTime"])
            if summary["schemaVersion"] != "cuefleet-backtest-v1" or actual != expected:
                raise ValueError(f"the {stage} replay does not match its frozen dataset")
            summaries.append(summary)
        daily, monthly = combined_periods(summaries, parts)
        report = {
            "schemaVersion": "cuefleet-quant-report-v1",
            "strategy": {"name": options.strategy_name, "revision": options.strategy_revision,
                         "hypothesis": options.hypothesis, "fileSha256": digest(options.strategy_file) if options.strategy_file else None},
            "symbol": options.symbol,
            "priceSource": PRICE_SOURCES[options.price_source],
            "priceSourceId": options.price_source,
            "dataset": manifest,
            "signalInputSha256": input_hash,
            "assumptions": summaries[0]["parameters"],
            "partitions": {stage: {**part, "summary": summary, "metrics": derived_metrics(part, summary)}
                           for stage, part, summary in zip(stages, parts, summaries)},
            "daily": daily,
            "monthly": monthly,
        }
        render_chart(report, result / "performance.png")
        shutil.copyfile(options.split_dir / "split-manifest.json", result / "split-manifest.json")
        (result / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        write_markdown(result / "report.md", report)
        if stages == TRAIN_TEST:
            write_markdown(result / "development-report.md", report, development=True)
        result.rename(output)
    print(output / "report.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-dir", type=Path, required=True)
    parser.add_argument("--signals", type=Path, required=True)
    parser.add_argument("--strategy-name", required=True)
    parser.add_argument("--strategy-revision", required=True)
    parser.add_argument("--hypothesis")
    parser.add_argument("--strategy-file", type=Path)
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT"), required=True)
    parser.add_argument("--price-source", choices=PRICE_SOURCES, default="binance-um-futures")
    parser.add_argument("--duration-minutes", type=int, choices=EVENT_CONTRACT_DURATIONS, required=True)
    parser.add_argument("--stake", required=True)
    parser.add_argument("--payout-ratio", required=True)
    parser.add_argument("--max-concurrent", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    try:
        run(parser.parse_args())
    except (OSError, ValueError, KeyError, TypeError, ImportError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"report: {error}\n")


if __name__ == "__main__":
    main()
