"""Export a CueFleet-compatible Python signal project as a self-contained folder."""

import argparse
import json
from pathlib import Path
import re
import shutil
import stat
from tempfile import TemporaryDirectory

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "signal-server"
VERSION = "cuefleet.signal.v1"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
SOURCES = ["binance-usdm-perpetual", "binance-usdm-index"]
INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
SKIP = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
# Match the whitespace removed by JavaScript String.trim().
NAME_EDGE_WHITESPACE = " \t\n\v\f\r\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def included_path(project, value):
    relative = Path(value)
    if relative.is_absolute() or relative.drive or not relative.parts or ".." in relative.parts:
        raise ValueError(f"--include must be a relative path inside --project: {value}")
    if relative.parts[0].lower() in {"cuefleet_signal", "readme-cuefleet.md"}:
        raise ValueError(f"Reserved export path: {value}")
    candidate = project
    for part in relative.parts:
        candidate = candidate / part
        if excluded(candidate) or is_link(candidate):
            raise ValueError(f"Unsupported export item: {value}")
    candidate.resolve(strict=True).relative_to(project)
    return relative


def excluded(item):
    name = item.name.lower()
    return name in SKIP or name == ".env" or name.startswith(".env.")


def is_link(item):
    attributes = getattr(item.lstat(), "st_file_attributes", 0)
    return item.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def check_tree(source):
    if is_link(source):
        raise ValueError(f"Symbolic links and junctions are unsupported: {source}")
    if source.is_dir():
        for item in source.iterdir():
            if not excluded(item):
                check_tree(item)
    elif not source.is_file():
        raise ValueError(f"Unsupported export item: {source}")


def ignored(_directory, names):
    return {name for name in names if excluded(Path(name))}


def check_options(options):
    project = options.project.resolve(strict=True) if options.project else None
    if options.include and not project:
        raise ValueError("--include requires --project")
    if project and not project.is_dir():
        raise ValueError("--project must be a directory")
    paths = [included_path(project, value) for value in options.include]
    for path in paths:
        if any(path != other and path.is_relative_to(other) for other in paths) or paths.count(path) > 1:
            raise ValueError(f"Overlapping --include entry: {path}")
        check_tree(project / path)
    if options.strategy and not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*", options.strategy):
        raise ValueError("--strategy must use module:function")
    if options.strategy and not paths:
        raise ValueError("--strategy requires the project code to be added with --include")
    if Path("requirements.lock") in paths and not (project / "requirements.lock").is_file():
        raise ValueError("requirements.lock must be a file")
    if options.requirements and (not options.requirements.is_file() or Path("requirements.lock") in paths):
        raise ValueError("Specify one requirements lock file")
    if not 1 <= options.warmup <= 600:
        raise ValueError("--warmup must be between 1 and 600; keep older history in your project")
    name = options.name
    if (not 1 <= len(name) <= 80 or name != name.strip(NAME_EDGE_WHITESPACE)
            or re.search(r"[\x00-\x1f\x7f]", name)):
        raise ValueError("--name must contain 1–80 characters with no surrounding whitespace or control characters")
    output = options.output.resolve()
    if output.exists():
        raise ValueError("The output folder must be a new folder")
    if any(output.is_relative_to(project / path) for path in paths):
        raise ValueError("The output folder must be outside each included tree")
    return project, paths, output


def populate_export(options, project, paths, output):
    output.mkdir()
    for path in paths:
        source, target = project / path, output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignored)
        else:
            shutil.copyfile(source, target)
    dependencies = output / "requirements.lock"
    if options.requirements:
        shutil.copyfile(options.requirements, dependencies)
    elif not dependencies.exists():
        dependencies.write_text("# Standard-library starter.\n", encoding="utf-8")

    server = output / "cuefleet_signal"
    shutil.copytree(TEMPLATE, server, ignore=lambda directory, names: ignored(directory, names) | {"README-CueFleet.md"})
    shutil.copyfile(TEMPLATE / "README-CueFleet.md", output / "README-CueFleet.md")
    selected = list(dict.fromkeys(options.symbol or ["ETHUSDT"]))
    config = {
        "version": VERSION,
        "name": options.name,
        "strategy": options.strategy or "cuefleet_signal.example_strategy:predict",
        "marketRequirements": [
            {
                "source": options.source,
                "symbol": symbol,
                "interval": options.interval,
                "minClosedCandles": options.warmup,
            }
            for symbol in selected
        ],
    }
    (server / "signal.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export(options):
    project, paths, output = check_options(options)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".cuefleet-export-", dir=output.parent) as staging:
        staged = Path(staging) / "project"
        populate_export(options, project, paths, staged)
        if output.exists():
            raise ValueError("The output folder must be a new folder")
        staged.rename(output)
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new project folder")
    parser.add_argument("--project", type=Path, help="existing project root")
    parser.add_argument("--include", action="append", default=[], help="project-relative file or folder; repeat as needed")
    parser.add_argument("--strategy", help="entry point in module:function form")
    parser.add_argument("--requirements", type=Path, help="hash-pinned pip requirements lock file")
    parser.add_argument("--name", default="CueFleet signal service")
    parser.add_argument("--symbol", action="append", choices=SYMBOLS, help="repeat to support both symbols")
    parser.add_argument("--source", choices=SOURCES, default=SOURCES[0])
    parser.add_argument("--interval", choices=INTERVALS, default="1m")
    parser.add_argument("--warmup", type=int, default=2, help="minimum number of consecutive closed candles")
    args = parser.parse_args()
    try:
        export(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
