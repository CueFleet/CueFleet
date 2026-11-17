"""Check interoperability with an independently implemented signal service."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import unittest
from uuid import UUID

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_signal_service.py"
TOKEN = "signal-check-fixture"
VERSION = "cuefleet.signal.v1"


@contextmanager
def external_service(response_mode="valid"):
    requests = []

    class Service(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, payload):
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self.send_error(401)
                return
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            requests.append((self.path, None))
            if response_mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "/redirected")
                self.end_headers()
                return
            self.reply({"version": VERSION, "name": "External Service", "marketRequirements": [
                {"symbol": "BTCUSDT", "source": "binance-usdm-perpetual", "interval": "1m", "minClosedCandles": 2},
                {"symbol": "ETHUSDT", "source": "binance-usdm-index", "interval": "4h", "minClosedCandles": 600},
            ]})

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, payload))
            self.reply({"version": VERSION, "decision": "SHORT",
                        "requestId": payload["requestId"] if response_mode != "bad-echo" else "other-id",
                        "observedAt": payload["market"]["asOf"]})

    with ThreadingHTTPServer(("127.0.0.1", 0), Service) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests
        finally:
            server.shutdown()
            thread.join()


class SignalServiceCheckerTest(unittest.TestCase):
    def run_check(self, address, *args, token=TOKEN):
        env = dict(os.environ, CUEFLEET_SIGNAL_TOKEN=token)
        return subprocess.run([sys.executable, str(CHECKER), "--url", address, *args],
                              env=env, text=True, capture_output=True, timeout=15)

    def test_checks_exactly_two_endpoints_as_advertised_by_external_service(self):
        with external_service() as (address, requests):
            outcome = self.run_check(address, "--symbol", "ETHUSDT", "--period", "1h")
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        result = json.loads(outcome.stdout)
        self.assertEqual((result["ok"], result["symbol"], result["period"], result["decision"]),
                         (True, "ETHUSDT", "1h", "SHORT"))
        self.assertNotIn(TOKEN, outcome.stdout)
        self.assertEqual([method for method, _ in requests], ["/health", "/v1/predict"])
        payload = requests[-1][1]
        self.assertEqual(UUID(payload["requestId"]).version, 4)
        market = payload["market"]
        self.assertEqual((market["source"], market["interval"]), ("binance-usdm-index", "4h"))
        candles = market["candles"]
        self.assertEqual(len(candles), 600)
        self.assertTrue(all(candle["volume"] is None for candle in candles))
        self.assertTrue(all(left["closeTime"] == right["openTime"] for left, right in zip(candles, candles[1:])))
        self.assertLessEqual(candles[-1]["closeTime"], market["asOf"])

    def test_rejects_bad_echo_and_does_not_follow_redirect(self):
        for mode, message, paths in [
            ("bad-echo", "invalid version, request ID", ["/health", "/v1/predict"]),
            ("redirect", "HTTP 302", ["/health"]),
        ]:
            with self.subTest(mode=mode), external_service(mode) as (address, requests):
                result = self.run_check(address)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn(TOKEN, result.stderr)
                self.assertEqual([path for path, _ in requests], paths)


if __name__ == "__main__":
    unittest.main()
