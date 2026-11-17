"""CueFleet v1 network adapter. The strategy owns feature engineering and inference."""

import argparse
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
import json
import os
from pathlib import Path
import re
from hmac import compare_digest
import sys
from threading import BoundedSemaphore, Lock
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
VERSION = "cuefleet.signal.v1"
SYMBOLS = {"BTCUSDT", "ETHUSDT"}
SOURCES = {"binance-usdm-index", "binance-usdm-perpetual"}
PERIODS = {"10m", "30m", "1h", "1d"}
INTERVALS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}
DECISIONS = {"LONG", "SHORT", "NO_SIGNAL"}
MAX_CANDLES = 600
MAX_BODY = 512 * 1024
# Match the whitespace removed by JavaScript String.trim().
NAME_EDGE_WHITESPACE = " \t\n\v\f\r\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def validate_requirement(value):
    if not isinstance(value, dict) or set(value) != {"source", "symbol", "interval", "minClosedCandles"}:
        raise ValueError("invalid_market_requirement")
    if any(not isinstance(value[key], str) for key in ("source", "symbol", "interval")):
        raise ValueError("invalid_market_requirement")
    length = value["minClosedCandles"]
    if (value["source"] not in SOURCES or value["symbol"] not in SYMBOLS
            or value["interval"] not in INTERVALS or type(length) is not int
            or not 1 <= length <= MAX_CANDLES):
        raise ValueError("invalid_market_requirement")
    return value


def market_candles(market, requirement):
    if not isinstance(market, dict) or set(market) != {"source", "interval", "asOf", "candles"}:
        raise ValueError("invalid_market")
    if (market["source"] != requirement["source"] or market["interval"] != requirement["interval"]
            or not timestamp(market["asOf"])):
        raise ValueError("invalid_market")
    candles = market["candles"]
    if not isinstance(candles, list) or not requirement["minClosedCandles"] <= len(candles) <= MAX_CANDLES:
        raise ValueError("invalid_candle_count")
    interval = INTERVALS[requirement["interval"]]
    previous_close = None
    for candle in candles:
        if not isinstance(candle, dict) or set(candle) != {
            "openTime", "closeTime", "open", "high", "low", "close", "volume",
        }:
            raise ValueError("invalid_candle")
        opened, closed = candle["openTime"], candle["closeTime"]
        if (not timestamp(opened) or not timestamp(closed) or opened % interval != 0
                or closed != opened + interval or closed > market["asOf"]
                or (previous_close is not None and opened != previous_close)):
            raise ValueError("invalid_candle_time")
        previous_close = closed
        opening, high, low, close = (price_decimal(candle[key]) for key in ("open", "high", "low", "close"))
        if not low <= min(opening, close) <= max(opening, close) <= high:
            raise ValueError("invalid_candle_price")
        if requirement["source"] == "binance-usdm-index":
            if candle["volume"] is not None:
                raise ValueError("invalid_index_volume")
        else:
            price_decimal(candle["volume"], allow_zero=True)


def timestamp(value):
    return type(value) is int and 0 < value <= 9_007_199_254_740_991


def price_decimal(value, *, allow_zero=False):
    if not isinstance(value, str) or len(value) > 48 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("invalid_decimal")
    number = Decimal(value)
    if not allow_zero and number == 0:
        raise ValueError("invalid_price")
    return number


def load_config():
    config = json.loads(Path(__file__).with_name("signal.json").read_text(encoding="utf-8"))
    if config.get("version", VERSION) != VERSION:
        raise ValueError("unsupported_signal_version")
    requirements = config["marketRequirements"]
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= len(SYMBOLS):
        raise ValueError("invalid_market_requirements")
    by_symbol = {item["symbol"]: item for item in map(validate_requirement, requirements)}
    if len(by_symbol) != len(requirements):
        raise ValueError("duplicate_symbol")
    name = config["name"]
    if (not isinstance(name, str) or not 1 <= len(name) <= 80
            or name != name.strip(NAME_EDGE_WHITESPACE) or re.search(r"[\x00-\x1f\x7f]", name)):
        raise ValueError("invalid_service_name")
    strategy = config["strategy"]
    if not isinstance(strategy, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*", strategy):
        raise ValueError("invalid_strategy_entrypoint")
    module, function = strategy.split(":")
    sys.path.insert(0, str(ROOT))
    predict = getattr(import_module(module), function)
    if not callable(predict):
        raise ValueError("invalid_strategy_callable")
    return {"version": VERSION, "name": name, "marketRequirements": requirements}, by_symbol, predict


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_json")
        result[key] = value
    return result


def parse_prediction(raw, by_symbol):
    def reject_constant(_value):
        raise ValueError("invalid_json")

    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("invalid_json") from None
    if not isinstance(value, dict) or set(value) != {"version", "requestId", "symbol", "period", "market"}:
        raise ValueError("invalid_prediction")
    if value["version"] != VERSION or not isinstance(value["symbol"], str) or value["symbol"] not in by_symbol:
        raise ValueError("unsupported_scene")
    if not isinstance(value["period"], str) or value["period"] not in PERIODS:
        raise ValueError("unsupported_scene")
    request_id = value["requestId"]
    if not isinstance(request_id, str) or not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", request_id, re.IGNORECASE):
        raise ValueError("invalid_request_id")
    UUID(request_id)
    market_candles(value["market"], by_symbol[value["symbol"]])
    return value


class SignalServer(ThreadingHTTPServer):
    daemon_threads = True

    slots = BoundedSemaphore(16)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(5)
        return sock, address


def handler_for(health, by_symbol, predict, token):
    busy = Lock()
    expected = f"Bearer {token}".encode("ascii") if token else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def send_json(self, status, value):
            data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def error(self, status, code):
            self.send_json(status, {"error": {"code": code}})

        def authorized(self):
            auth = self.headers.get_all("Authorization") or []
            if expected is None or (len(auth) == 1 and compare_digest(auth[0].encode("latin-1"), expected)):
                return True
            self.error(401, "unauthorized")
            return False

        def do_GET(self):
            if self.path != "/health":
                return self.error(404, "not_found")
            if self.authorized():
                self.send_json(200, health)

        def do_POST(self):
            if self.path != "/v1/predict":
                return self.error(404, "not_found")
            if not self.authorized():
                return
            if (len(self.headers.get_all("Content-Type") or []) != 1
                    or self.headers.get_content_type() != "application/json"
                    or self.headers.get("Transfer-Encoding") is not None):
                return self.error(415, "unsupported_body")
            length = self.headers.get_all("Content-Length") or []
            if len(length) != 1 or not re.fullmatch(r"[0-9]{1,10}", length[0]):
                return self.error(400, "invalid_content_length")
            size = int(length[0])
            if size > MAX_BODY:
                return self.error(413, "request_too_large")
            try:
                raw = self.rfile.read(size)
            except TimeoutError:
                return self.error(408, "request_timeout")
            if len(raw) != size:
                return self.error(400, "incomplete_body")
            try:
                request = parse_prediction(raw, by_symbol)
            except ValueError as error:
                return self.error(400, str(error))
            request_id = request["requestId"]
            observed_at = request["market"]["asOf"]
            if not busy.acquire(blocking=False):
                return self.error(429, "strategy_busy")
            try:
                decision = predict(request)
                if not isinstance(decision, str) or decision not in DECISIONS:
                    raise ValueError("invalid_strategy_signal")
            except Exception as error:
                print(f"CueFleet prediction failed: {type(error).__name__}", file=sys.stderr)
                return self.error(500, "strategy_failed")
            finally:
                busy.release()
            self.send_json(200, {
                "version": VERSION,
                "requestId": request_id,
                "observedAt": observed_at,
                "decision": decision,
            })

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Run a CueFleet signal project on this machine.")
    parser.add_argument("--port", type=int, default=18781)
    options = parser.parse_args()
    if not 0 <= options.port <= 65535:
        parser.error("port must be between 0 and 65535")
    token = os.environ.get("CUEFLEET_SIGNAL_TOKEN", "")
    if token and not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,512}", token):
        parser.error("CUEFLEET_SIGNAL_TOKEN must contain 1–512 characters from A–Z, a–z, 0–9 and ._~+/=-")
    health, requirements, predict = load_config()
    with SignalServer(("127.0.0.1", options.port), handler_for(health, requirements, predict, token)) as server:
        print(f"http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
