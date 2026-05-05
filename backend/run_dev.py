#!/usr/bin/env python3
"""Dev server launcher: fails fast if PORT is busy (clearer than uvicorn errno 98)."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _port_in_use(port: int) -> bool:
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.settimeout(0.4)
    try:
        return sk.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sk.close()


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    if _port_in_use(port):
        print(
            f"Port {port} is already in use (another process is listening).\n"
            f"  • Stop it: e.g. `ss -lptn 'sport = :{port}'` then stop the listed PID, or\n"
            f"  • Use another port: `PORT=8001 python run_dev.py`",
            file=sys.stderr,
        )
        sys.exit(1)

    os.chdir(ROOT)
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ],
    )


if __name__ == "__main__":
    main()
