"""Create the isolated project virtual environment, then start the service."""

from hashlib import sha256
from pathlib import Path
import os
import platform
import subprocess
import sys
from venv import EnvBuilder


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("CueFleet signal projects require Python 3.11 or newer.")
    here = Path(__file__).resolve().parent
    root = here.parent
    lock = root / "requirements.lock"
    contents = lock.read_bytes()
    install = any(line.strip() and not line.lstrip().startswith(b"#") for line in contents.splitlines())
    identity = repr((sys.implementation.name, sys.version_info[:3], os.name, platform.machine(), sys.executable))
    revision = sha256(identity.encode("utf-8") + b"\0" + contents).hexdigest()[:24]
    env = root / ".venv" / revision
    env.mkdir(parents=True, exist_ok=True)
    lock_dir = env / ".setup"
    ready = env / ".ready"
    interpreter = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.is_file() or not ready.is_file():
        try:
            lock_dir.mkdir()
        except FileExistsError:
            raise SystemExit(f"Environment setup is busy. If setup was interrupted, clear {lock_dir}.") from None
        try:
            if not interpreter.is_file():
                EnvBuilder(with_pip=install).create(env)
            if install:
                subprocess.run(
                    [interpreter, "-m", "pip", "install", "--require-hashes", "-r", lock],
                    cwd=root, check=True,
                )
            ready.touch()
        finally:
            lock_dir.rmdir()
    if sys.argv[1:] == ["--prepare"]:
        print(interpreter)
        return 0
    return subprocess.call([interpreter, here / "serve.py", *sys.argv[1:]], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
