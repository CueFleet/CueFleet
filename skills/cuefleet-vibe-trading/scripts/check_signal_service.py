"""Check a CueFleet signal service with synthetic, uniformly closed candles."""

import argparse
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
from time import monotonic, time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "templates" / "signal-server"))
from serve import (  # noqa: E402
    DECISIONS, INTERVALS, NAME_EDGE_WHITESPACE, PERIODS, SYMBOLS, VERSION,
    unique_object, validate_requirement,
)

MAX_RESPONSE_BYTES = 16 * 1024
TIMEOUT_SECONDS = 6.5
MAX_SIGNAL_AGE_MS = 30_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def origin(value):
    if len(value) > 300 or re.search(r"[\s\\]", value):
        raise ValueError("Use a signal service origin, such as http://127.0.0.1:18781")
    url = urlsplit(value)
    loopback = url.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not url.hostname or url.username is not None or url.password is not None
        or url.query or url.fragment or url.path not in {"", "/"} or url.port == 0
        or (url.scheme != "https" and not (url.scheme == "http" and loopback))
    ):
        raise ValueError("Use HTTPS for a remote service or HTTP on loopback")
    return f"{url.scheme}://{url.netloc}"


def request_json(opener, address, route, token, payload=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = Request(address + route, headers=headers, data=body)
    deadline = monotonic() + TIMEOUT_SECONDS
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.headers.get_content_type() != "application/json":
                raise ValueError(f"{route} must return application/json")
            raw = bytearray()
            while True:
                if monotonic() > deadline:
                    raise ValueError(f"{route} timed out")
                data = response.read1(MAX_RESPONSE_BYTES + 1 - len(raw))
                if not data:
                    break
                raw.extend(data)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"{route} response exceeds 16 KiB")
    except HTTPError as error:
        error.close()
        raise ValueError(f"{route} returned HTTP {error.code}") from None
    except (OSError, HTTPException) as error:
        raise ValueError(f"{route} could not be reached") from error
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError(f"{route} returned invalid UTF-8 JSON") from None


def validate_health(health):
    if not isinstance(health, dict) or set(health) != {"version", "name", "marketRequirements"}:
        raise ValueError("/health must return version, name and marketRequirements")
    if health["version"] != VERSION:
        raise ValueError(f"/health must advertise {VERSION}")
    name = health["name"]
    if (not isinstance(name, str) or not 1 <= len(name) <= 80
            or name != name.strip(NAME_EDGE_WHITESPACE) or re.search(r"[\x00-\x1f\x7f]", name)):
        raise ValueError("/health returned an invalid name")
    requirements = health["marketRequirements"]
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= len(SYMBOLS):
        raise ValueError("/health must advertise one market window per supported symbol")
    windows = {item["symbol"]: item for item in map(validate_requirement, requirements)}
    if len(windows) != len(requirements):
        raise ValueError("/health advertised duplicate symbols")
    return windows


def prediction_input(requirement, period):
    as_of = int(time() * 1000)
    interval = INTERVALS[requirement["interval"]]
    latest_close = as_of // interval * interval
    first_open = latest_close - requirement["minClosedCandles"] * interval
    volume = None if requirement["source"] == "binance-usdm-index" else "1.50"
    candles = [
        {"openTime": opened, "closeTime": opened + interval,
         "open": str(price), "high": str(price + 2), "low": str(price - 1),
         "close": str(price + 1), "volume": volume}
        for price, opened in enumerate(range(first_open, latest_close, interval), start=2000)
    ]
    return {
        "version": VERSION, "requestId": str(uuid4()), "symbol": requirement["symbol"], "period": period,
        "market": {"source": requirement["source"], "interval": requirement["interval"],
                   "asOf": as_of, "candles": candles},
    }


def check(url, symbol, period, token):
    address = origin(url)
    if token and not re.fullmatch(r"[A-Za-z0-9._~+\/=-]{1,512}", token):
        raise ValueError("CUEFLEET_SIGNAL_TOKEN has an invalid format")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    health = request_json(opener, address, "/health", token)
    windows = validate_health(health)
    requirement = windows.get(symbol) if symbol else next(iter(windows.values()))
    if not requirement:
        raise ValueError(f"/health did not advertise {symbol}")
    payload = prediction_input(requirement, period)
    result = request_json(opener, address, "/v1/predict", token, payload)
    if (
        not isinstance(result, dict) or set(result) != {"version", "requestId", "decision", "observedAt"}
        or result["version"] != VERSION or result["requestId"] != payload["requestId"]
        or not isinstance(result["decision"], str) or result["decision"] not in DECISIONS
        or type(result["observedAt"]) is not int or result["observedAt"] != payload["market"]["asOf"]
    ):
        raise ValueError("/v1/predict returned an invalid version, request ID, direction or observation time")
    age = int(time() * 1000) - result["observedAt"]
    if not 0 <= age <= MAX_SIGNAL_AGE_MS:
        raise ValueError("/v1/predict returned a stale or future observation time")
    return {"ok": True, "name": health["name"], "version": VERSION, "symbol": payload["symbol"],
            "period": period, "decision": result["decision"], "observedAt": result["observedAt"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="signal service origin")
    parser.add_argument("--symbol", choices=sorted(SYMBOLS), help="defaults to the first advertised symbol")
    parser.add_argument("--period", choices=sorted(PERIODS), default="10m")
    args = parser.parse_args()
    try:
        result = check(args.url, args.symbol, args.period, os.environ.get("CUEFLEET_SIGNAL_TOKEN", ""))
    except ValueError as error:
        parser.exit(1, f"Signal service check failed: {error}\n")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
