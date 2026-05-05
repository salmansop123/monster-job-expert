import asyncio
import logging
import platform
import shutil
import subprocess
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CHROME_CANDIDATES = {
    "linux": [
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\{username}\AppData\Local\Google\Chrome\Application\chrome.exe",
    ],
}


def detect_os() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "windows"
    return "linux"


def find_chrome_binary() -> str | None:
    os_name = detect_os()
    candidates = CHROME_CANDIDATES.get(os_name, CHROME_CANDIDATES["linux"])
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return None


async def is_cdp_running(cdp_url: str = "http://localhost:9222") -> bool:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{cdp_url}/json/version", timeout=2.0)
            return resp.status_code == 200
    except Exception:
        return False


async def launch_chrome(
    cdp_url: str = "http://localhost:9222",
    user_data_dir: str = "/tmp/chrome-monster-profile",
) -> dict:
    os_name = detect_os()
    if await is_cdp_running(cdp_url):
        logger.info("Chrome CDP already running - skipping launch")
        return {"status": "already_running", "os": os_name, "cdp_url": cdp_url}

    binary = find_chrome_binary()
    if not binary:
        msg = f"Chrome binary not found on {os_name}. Install Google Chrome and retry."
        logger.error(msg)
        return {"status": "binary_not_found", "os": os_name, "error": msg}

    if os_name == "windows":
        user_data_dir = r"C:\chrome-monster-profile"
    elif os_name == "darwin":
        user_data_dir = str(Path.home() / "chrome-monster-profile")

    port = cdp_url.rsplit(":", 1)[-1]
    cmd = [
        binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
    ]
    logger.info("Launching Chrome on %s: %s", os_name, " ".join(cmd))
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "launch_failed",
            "os": os_name,
            "binary": binary,
            "error": str(exc),
        }

    for i in range(15):
        await asyncio.sleep(1)
        if await is_cdp_running(cdp_url):
            logger.info("Chrome CDP ready after %ss at %s", i + 1, cdp_url)
            return {
                "status": "launched",
                "os": os_name,
                "binary": binary,
                "cdp_url": cdp_url,
                "user_data_dir": user_data_dir,
            }

    return {
        "status": "timeout",
        "os": os_name,
        "binary": binary,
        "error": "Chrome launched but CDP not ready after 15 seconds",
    }
