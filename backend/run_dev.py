#!/usr/bin/env python3
"""Dev server launcher: fails fast if PORT is busy (clearer than uvicorn errno 98)."""

from __future__ import annotations

import os
import socket
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEBUG_LOG_PATH = ROOT.parent / ".cursor" / "debug-e26ce4.log"


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "e26ce4",
            "runId": "run1",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # #endregion


def _port_in_use(port: int) -> bool:
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.settimeout(0.4)
    try:
        return sk.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sk.close()


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    _debug_log(
        "H1",
        "backend/run_dev.py:main",
        "run_dev entry",
        {
            "port_env": os.environ.get("PORT"),
            "resolved_port": port,
            "cwd": str(Path.cwd()),
            "python": sys.executable,
        },
    )
    if _port_in_use(port):
        _debug_log(
            "H1",
            "backend/run_dev.py:main",
            "port already in use; backend will exit",
            {"port": port},
        )
        print(
            f"Port {port} is already in use (another process is listening).\n"
            f"  • Stop it: e.g. `ss -lptn 'sport = :{port}'` then stop the listed PID, or\n"
            f"  • Use another port: `PORT=8001 python run_dev.py`",
            file=sys.stderr,
        )
        sys.exit(1)

    os.chdir(ROOT)
    _debug_log(
        "H4",
        "backend/run_dev.py:main",
        "executing uvicorn",
        {"host": "0.0.0.0", "port": port, "app": "app.main:app"},
    )
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
