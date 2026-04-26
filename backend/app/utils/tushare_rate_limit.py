from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None


ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATE_DIR = ROOT / "data" / "run"
STATE_FILE = STATE_DIR / "tushare_rate_limit.json"
LOCK_FILE = STATE_DIR / "tushare_rate_limit.lock"

WINDOW_SECONDS = int(os.environ.get("TUSHARE_RATE_LIMIT_WINDOW_SECONDS", "60"))
MAX_REQUESTS_PER_WINDOW = int(os.environ.get("TUSHARE_MAX_REQUESTS_PER_MINUTE", "800"))


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"timestamps": []}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"timestamps": []}


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def acquire_tushare_slot(endpoint: str = "unknown") -> None:
    del endpoint

    if MAX_REQUESTS_PER_WINDOW <= 0 or WINDOW_SECONDS <= 0:
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not LOCK_FILE.exists():
        LOCK_FILE.write_text("0", encoding="utf-8")

    while True:
        with LOCK_FILE.open("r+", encoding="utf-8") as lock_handle:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:
                lock_handle.seek(0)
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)

            try:
                state = _load_state()
                now = time.time()
                timestamps = [
                    float(ts)
                    for ts in state.get("timestamps", [])
                    if isinstance(ts, (int, float)) or str(ts).replace(".", "", 1).isdigit()
                ]
                timestamps = [ts for ts in timestamps if now - ts < WINDOW_SECONDS]

                if len(timestamps) < MAX_REQUESTS_PER_WINDOW:
                    timestamps.append(now)
                    _save_state({"timestamps": timestamps})
                    return

                wait_seconds = max(0.05, WINDOW_SECONDS - (now - timestamps[0]) + 0.01)
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    lock_handle.seek(0)
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)

        time.sleep(wait_seconds)
