"""Integration contract for exported CueFleet signal projects."""

from contextlib import contextmanager
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

EXPORTER = Path(__file__).resolve().parents[1] / "scripts" / "signal_project.py"
VERSION = "cuefleet.signal.v1"
OPEN = 1_760_000_040_000
TOKEN = "fixture-local-bearer._~+/="
OPENER = build_opener(ProxyHandler({}))


def run_export(*args):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(EXPORTER), *map(str, args)],
        check=True, capture_output=True, encoding="utf-8", timeout=15,
    )


def prediction(*, source="binance-usdm-perpetual", gap=False, count=2):
    candles = []
    for index in range(count):
        open_time = OPEN + index * 60_000 + (60_000 if gap and index > 0 else 0)
        candles.append({
            "openTime": open_time, "closeTime": open_time + 60_000,
            "open": "2410.10", "high": "2412.38", "low": "2410.01",
            "close": "2411.00", "volume": None if source == "binance-usdm-index" else "4.06",
        })
    return {
        "version": VERSION, "requestId": str(uuid4()), "symbol": "ETHUSDT", "period": "10m",
        "market": {"source": source, "interval": "1m", "asOf": OPEN + 240_000, "candles": candles},
    }


def http(url, payload=None, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    request = Request(url, headers=headers, data=data)
    with OPENER.open(request, timeout=5) as response:
        return json.load(response)


@contextmanager
def running_service(folder, *, token=None):
    bootstrap = folder / "cuefleet_signal/start.py"
    environment = subprocess.check_output(
        [sys.executable, "-X", "utf8", str(bootstrap), "--prepare"], cwd=folder, encoding="utf-8", timeout=30,
    ).splitlines()[-1]
    assert Path(environment).resolve().is_relative_to(folder / ".venv")
    env = os.environ.copy()
    if token:
        env["CUEFLEET_SIGNAL_TOKEN"] = token
    else:
        env.pop("CUEFLEET_SIGNAL_TOKEN", None)
    child = subprocess.Popen(
        [environment, "-X", "utf8", str(folder / "cuefleet_signal/serve.py"), "--port", "0"],
        cwd=folder, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
    )
    ready = queue.Queue()
    Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
    try:
        address = ready.get(timeout=10).strip()
        if not address.startswith("http://127.0.0.1:"):
            raise RuntimeError(f"Signal server failed to start: {child.stderr.read()}")
        yield address
    finally:
        child.terminate()
        child.communicate(timeout=5)


class SignalProjectTest(unittest.TestCase):
    def test_export_complex_project_and_serve_real_adapter(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            project = root / "source"
            output = root / "exported project"
            (project / "strategy_pkg").mkdir(parents=True)
            (project / "weights").mkdir()
            (project / "weights/class.txt").write_text("LONG", encoding="utf-8")
            (project / "strategy_pkg/.env").write_text("must-not-be-exported", encoding="utf-8")
            (project / "strategy_pkg/__init__.py").write_text(
                "from pathlib import Path\n"
                "def predict(request):\n"
                "    assert len(request['market']['candles']) == 2\n"
                "    return Path('weights/class.txt').read_text(encoding='utf-8')\n", encoding="utf-8",
            )
            run_export(
                "--output", output, "--project", project, "--include", "strategy_pkg",
                "--include", "weights", "--strategy", "strategy_pkg:predict", "--name", "example NN",
            )
            self.assertTrue((output / "README-CueFleet.md").is_file())
            self.assertFalse((output / "strategy_pkg/.env").exists())
            with running_service(output, token=TOKEN) as address:
                with self.assertRaises(HTTPError) as denied:
                    http(address + "/health")
                self.assertEqual(denied.exception.code, 401)
                denied.exception.close()
                self.assertEqual(http(address + "/health", token=TOKEN), {
                    "version": VERSION, "name": "example NN",
                    "marketRequirements": [{
                        "source": "binance-usdm-perpetual", "symbol": "ETHUSDT", "interval": "1m", "minClosedCandles": 2,
                    }],
                })
                request = prediction()
                self.assertEqual(http(address + "/v1/predict", request, TOKEN), {
                    "version": VERSION, "requestId": request["requestId"], "decision": "LONG",
                    "observedAt": request["market"]["asOf"],
                })
                for bad in (prediction(gap=True), prediction(count=1), prediction(source="binance-usdm-index")):
                    with self.assertRaises(HTTPError) as invalid:
                        http(address + "/v1/predict", bad, TOKEN)
                    self.assertEqual(invalid.exception.code, 400)
                    invalid.exception.close()

    def test_starter_accepts_index_bars_and_returns_neutral_signal(self):
        with TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "export"
            run_export("--output", output, "--source", "binance-usdm-index")
            with running_service(output) as address:
                request = prediction(source="binance-usdm-index")
                self.assertEqual(http(address + "/v1/predict", request)["decision"], "NO_SIGNAL")
                request["market"]["candles"][0]["volume"] = "12"
                with self.assertRaises(HTTPError) as invalid:
                    http(address + "/v1/predict", request)
                self.assertEqual(invalid.exception.code, 400)
                invalid.exception.close()

    def test_export_versions_manifest_and_legacy_manifest_still_starts(self):
        with TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "export"
            run_export("--output", output)
            manifest = output / "cuefleet_signal/signal.json"
            config = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(config.pop("version"), VERSION)
            manifest.write_text(json.dumps(config), encoding="utf-8")
            with running_service(output) as address:
                self.assertEqual(http(address + "/health")["version"], VERSION)
                self.assertEqual(http(address + "/v1/predict", prediction())["decision"], "NO_SIGNAL")

            config["version"] = "cuefleet.signal.v2"
            manifest.write_text(json.dumps(config), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(output / "cuefleet_signal/serve.py"), "--port", "0"],
                cwd=output, env=dict(os.environ, CUEFLEET_SIGNAL_TOKEN=""), capture_output=True, encoding="utf-8", timeout=5,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported_signal_version", result.stderr)

    def test_rejects_duplicate_json_keys_and_invalid_body_framing(self):
        with TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "export"
            run_export("--output", output)
            with running_service(output) as address:
                service = urlsplit(address)
                body = json.dumps(prediction()).replace('"period": "10m"', '"period":"10m","period":"10m"').encode()
                for headers, payload, expected in (
                    ([("Content-Length", str(len(body)))], body, 400),
                    ([("Content-Length", "0"), ("Content-Length", "0")], b"", 400),
                    ([("Content-Length", "nope")], b"", 400),
                    ([("Content-Length", "900000")], b"", 413),
                    ([("Transfer-Encoding", "chunked")], b"", 415),
                ):
                    client = HTTPConnection(service.hostname, service.port, timeout=5)
                    try:
                        client.putrequest("POST", "/v1/predict")
                        client.putheader("Content-Type", "application/json")
                        for key, value in headers:
                            client.putheader(key, value)
                        client.endheaders(payload)
                        with client.getresponse() as response:
                            self.assertEqual(response.status, expected)
                    finally:
                        client.close()

    def test_service_names_use_eighty_unicode_code_points_without_edge_whitespace(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "export"
            name = "卫星🛰" * 26 + "🚀🧭"
            self.assertEqual(len(name), 80)
            run_export("--output", output, "--name", name)
            with running_service(output) as address:
                self.assertEqual(http(address + "/health")["name"], name)
            config_file = output / "cuefleet_signal/signal.json"
            config = json.loads(config_file.read_text(encoding="utf-8"))
            env = dict(os.environ, CUEFLEET_SIGNAL_TOKEN="")
            for invalid in (name + "🚀", " left", "right\u00a0", "\ufeffname", "invalid\x7finside"):
                with self.assertRaises(subprocess.CalledProcessError):
                    run_export("--output", root / "rejected", "--name", invalid)
                self.assertFalse((root / "rejected").exists())
                config["name"] = invalid
                config_file.write_text(json.dumps(config), encoding="utf-8")
                startup = subprocess.run(
                    [sys.executable, "-X", "utf8", str(output / "cuefleet_signal/serve.py"), "--port", "0"],
                    cwd=output, env=env, capture_output=True, encoding="utf-8", timeout=5,
                )
                self.assertNotEqual(startup.returncode, 0)
                self.assertIn("invalid_service_name", startup.stderr)

    def test_rejects_invalid_token_before_listening(self):
        with TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "export"
            run_export("--output", output)
            for token in (" leading", "trailing\n", "token%", "秘密", "a" * 513):
                env = dict(os.environ, CUEFLEET_SIGNAL_TOKEN=token)
                startup = subprocess.run(
                    [sys.executable, "-X", "utf8", str(output / "cuefleet_signal/serve.py"), "--port", "0"],
                    cwd=output, env=env, capture_output=True, encoding="utf-8", timeout=5,
                )
                self.assertNotEqual(startup.returncode, 0)
                self.assertIn("CUEFLEET_SIGNAL_TOKEN", startup.stderr)

    def test_export_rejects_overwriting_an_existing_folder_and_path_traversal(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "test.txt").write_text("unchanged", encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError):
                run_export("--output", root)
            self.assertEqual((root / "test.txt").read_text(encoding="utf-8"), "unchanged")
            with self.assertRaises(subprocess.CalledProcessError):
                run_export("--output", root / "export", "--project", root, "--include", "../test.txt")
            self.assertFalse((root / "export").exists())


if __name__ == "__main__":
    unittest.main()
