#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

if (
    os.environ.get("STOCKTRADE_BACKGROUND_UPDATE_BOOTSTRAPPED") != "1"
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
):
    env = dict(os.environ)
    env["STOCKTRADE_BACKGROUND_UPDATE_BOOTSTRAPPED"] = "1"
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]], env)

pythonpath_entries = [entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry]
for required_path in (str(ROOT), str(BACKEND)):
    if required_path not in pythonpath_entries:
        pythonpath_entries.append(required_path)
    if required_path not in sys.path:
        sys.path.insert(0, required_path)
if pythonpath_entries:
    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from app.config import settings
from app.services.background_update_exceptions import RetryableBackgroundUpdateError
from app.services.background_update_service import BackgroundLatestTradeDayUpdateService

TEMPFAIL_EXIT_CODE = 75


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="后台最新交易日更新脚本")
    parser.add_argument("--target-date", default=None, help="指定交易日，格式 YYYY-MM-DD")
    parser.add_argument("--reviewer", default="quant", help="明日之星 reviewer，默认 quant")
    parser.add_argument("--window-size", type=int, default=180, help="明日之星窗口大小，默认 180")
    parser.add_argument("--force", action="store_true", help="忽略最新性检查，强制执行")
    parser.add_argument(
        "--log-file",
        default=str(Path(settings.logs_dir) / "async_latest_trade_day_update.log"),
        help="日志文件路径",
    )
    parser.add_argument(
        "--lock-file",
        default=str(Path(settings.data_dir) / "run" / "async_latest_trade_day_update.lock"),
        help="进程锁文件路径",
    )
    return parser.parse_args()


def configure_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.unlink(missing_ok=True)

    task_logger = logging.getLogger("background_latest_trade_day_update")
    task_logger.setLevel(logging.INFO)
    task_logger.handlers.clear()
    task_logger.propagate = False

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    task_logger.addHandler(file_handler)
    task_logger.addHandler(stream_handler)
    return task_logger


def acquire_lock(lock_file: Path):
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    fp = lock_file.open("w", encoding="utf-8")
    fp.write(str(os.getpid()))
    fp.flush()

    if fcntl is None:  # pragma: no cover
        return fp

    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fp.close()
        raise RuntimeError(f"已有后台更新进程在运行，锁文件: {lock_file}")
    return fp


def release_lock(lock_fp) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
    finally:
        lock_fp.close()


def main() -> int:
    args = parse_args()
    log_file = Path(args.log_file)
    lock_file = Path(args.lock_file)
    task_logger = configure_logging(log_file)

    lock_fp = None
    try:
        lock_fp = acquire_lock(lock_file)
        task_logger.info("后台更新任务启动 pid=%s", os.getpid())

        service = BackgroundLatestTradeDayUpdateService(log=task_logger)
        result = service.run(
            target_trade_date=args.target_date,
            reviewer=args.reviewer,
            window_size=args.window_size,
            force=args.force,
        )
        task_logger.info("任务结果: %s", json.dumps(result, ensure_ascii=False, default=str))
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
        return 0
    except RetryableBackgroundUpdateError as exc:
        task_logger.warning("后台更新稍后重试: %s", exc)
        return TEMPFAIL_EXIT_CODE
    except Exception as exc:
        task_logger.exception("后台更新失败: %s", exc)
        return 1
    finally:
        if lock_fp is not None:
            release_lock(lock_fp)


if __name__ == "__main__":
    raise SystemExit(main())
