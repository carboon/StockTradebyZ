from __future__ import annotations

import json
import os
import time
import tempfile
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
FALLBACK_STATE_DIR = Path(tempfile.gettempdir()) / "stocktrade_run"

WINDOW_SECONDS = int(os.environ.get("TUSHARE_RATE_LIMIT_WINDOW_SECONDS", "60"))
# 提高默认限流阈值以加速数据抓取
MAX_REQUESTS_PER_WINDOW = int(os.environ.get("TUSHARE_MAX_REQUESTS_PER_MINUTE", "5000"))
# 设置环境变量 TUSHARE_NO_RATE_LIMIT=1 可完全跳过限流
NO_RATE_LIMIT = os.environ.get("TUSHARE_NO_RATE_LIMIT", "0") == "1"


def _resolve_state_paths() -> tuple[Path, Path]:
    """Resolve writable state paths for rate limiting.

    Some container bind-mount setups can surface `/app/data/run` as an invalid
    path at runtime. Fall back to a local temp directory so Tushare checks and
    updates do not fail just because the rate-limit state file can't be created
    under the shared data mount.
    """
    for base_dir in (STATE_DIR, FALLBACK_STATE_DIR):
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            if not base_dir.is_dir():
                raise NotADirectoryError(str(base_dir))
            state_file = base_dir / "tushare_rate_limit.json"
            lock_file = base_dir / "tushare_rate_limit.lock"
            return state_file, lock_file
        except OSError:
            continue
    raise NotADirectoryError(str(STATE_DIR))


def _load_state() -> dict[str, Any]:
    state_file, _ = _resolve_state_paths()
    if not state_file.exists():
        return {"timestamps": []}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {"timestamps": []}


def _save_state(state: dict[str, Any]) -> None:
    state_file, _ = _resolve_state_paths()
    state_file.write_text(json.dumps(state), encoding="utf-8")


def acquire_tushare_slot(endpoint: str = "unknown") -> None:
    del endpoint

    # 完全跳过限流检查以加速
    if NO_RATE_LIMIT or MAX_REQUESTS_PER_WINDOW <= 0 or WINDOW_SECONDS <= 0:
        return

    _, lock_file = _resolve_state_paths()
    if not lock_file.exists():
        lock_file.write_text("0", encoding="utf-8")

    while True:
        with lock_file.open("r+", encoding="utf-8") as lock_handle:
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
