"""
Market Service
~~~~~~~~~~~~~~~
市场数据服务：获取最新交易日，判断数据是否需要更新，增量更新
"""
import json
import os
import pickle
import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable

import pandas as pd
from app.services.daily_batch_update_service import DailyBatchUpdateService
from app.time_utils import utc_now
from app.utils.stock_metadata import resolve_ts_code
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).parent.parent.parent.parent
CACHE_DIR = ROOT / "data" / "cache"
MARKET_CACHE_FILE = ROOT / "data" / ".market_cache.json"
PREPARED_CACHE_PREFIX = "prepared_data"
RUN_DIR = ROOT / "data" / "run"
INCREMENTAL_CHECKPOINT_VERSION = 1
logger = logging.getLogger(__name__)

# 全局更新状态
_update_state = {
    "status": "idle",
    "running": False,
    "task_id": None,
    "task_type": "incremental_update",
    "mode": "idle",
    "target_trade_date": None,
    "stage_label": None,
    "progress": 0,
    "current": 0,
    "total": 0,
    "current_code": None,
    "updated_count": 0,
    "skipped_count": 0,
    "failed_count": 0,
    "started_at": None,
    "completed_at": None,
    "eta_seconds": None,
    "elapsed_seconds": 0,
    "resume_supported": True,
    "initial_completed": 0,
    "completed_in_run": 0,
    "checkpoint_path": None,
    "last_error": None,
    "message": "",
}
_update_lock = threading.Lock()


class MarketService:
    """市场数据服务"""

    @staticmethod
    def _state_now() -> datetime:
        return utc_now()

    @staticmethod
    def _parse_state_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except Exception:
            return None
        if parsed.tzinfo is None:
            return parsed.astimezone()
        return parsed

    @classmethod
    def _elapsed_seconds_since(cls, started_at_value: Optional[str]) -> int:
        started_at = cls._parse_state_datetime(started_at_value)
        if started_at is None:
            return 0
        return max(0, int((cls._state_now() - started_at).total_seconds()))

    def __init__(self, token: Optional[str] = None):
        if token is not None:
            self.token = token
        else:
            from app.config import settings
            self.token = os.environ.get("TUSHARE_TOKEN", "") or settings.tushare_token
        self._pro = None
        self._cache = self._load_cache()

    @staticmethod
    def get_update_state() -> Dict[str, Any]:
        """获取增量更新状态"""
        with _update_lock:
            return _update_state.copy()

    @staticmethod
    def _normalize_end_date(end_date: Optional[str]) -> str:
        if end_date:
            return end_date.replace("-", "")
        return utc_now().strftime("%Y%m%d")

    @staticmethod
    def _display_trade_date(compact_trade_date: str) -> str:
        if len(compact_trade_date) == 8 and compact_trade_date.isdigit():
            return f"{compact_trade_date[:4]}-{compact_trade_date[4:6]}-{compact_trade_date[6:]}"
        return compact_trade_date

    @staticmethod
    def _build_incremental_checkpoint_path(codes: list[str], end_date: str, raw_dir: Path) -> Path:
        identity = {
            "version": INCREMENTAL_CHECKPOINT_VERSION,
            "end_date": end_date,
            "raw_dir": str(raw_dir.resolve()),
            "codes_hash": hashlib.sha1(",".join(codes).encode("utf-8")).hexdigest(),
        }
        digest = hashlib.sha1(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return RUN_DIR / f"incremental_update_{digest}.json"

    @staticmethod
    def _load_incremental_checkpoint(path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _restore_incremental_checkpoint(checkpoint: Optional[Dict[str, Any]], codes: list[str]) -> tuple[set[str], dict[str, str]]:
        if not checkpoint:
            return set(), {}

        code_set = set(codes)
        completed = {
            str(code)
            for code in checkpoint.get("completed_codes", [])
            if str(code) in code_set
        }
        failed_raw = checkpoint.get("failed_codes", {})
        failed: dict[str, str] = {}
        if isinstance(failed_raw, dict):
            for code, reason in failed_raw.items():
                code_str = str(code)
                if code_str in code_set and code_str not in completed:
                    failed[code_str] = str(reason or "更新失败")
        return completed, failed

    @staticmethod
    def _save_incremental_checkpoint(
        path: Path,
        *,
        codes: list[str],
        end_date: str,
        raw_dir: Path,
        completed_codes: set[str],
        failed_codes: dict[str, str],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INCREMENTAL_CHECKPOINT_VERSION,
            "updated_at": utc_now().isoformat(),
            "end_date": end_date,
            "raw_dir": str(raw_dir.resolve()),
            "total": len(codes),
            "completed_codes": sorted(completed_codes),
            "failed_codes": failed_codes,
            "resume_supported": True,
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(path)

    @staticmethod
    def _clear_incremental_checkpoint(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def start_update(task_id: Optional[int] = None) -> bool:
        """开始更新，返回是否成功（如果已有任务在运行则返回 False）"""
        with _update_lock:
            if _update_state["running"]:
                return False
            _update_state["status"] = "running"
            _update_state["running"] = True
            _update_state["task_id"] = task_id
            _update_state["task_type"] = "incremental_update"
            _update_state["mode"] = "pending"
            _update_state["target_trade_date"] = None
            _update_state["stage_label"] = None
            _update_state["progress"] = 0
            _update_state["current"] = 0
            _update_state["total"] = 0
            _update_state["current_code"] = None
            _update_state["updated_count"] = 0
            _update_state["skipped_count"] = 0
            _update_state["failed_count"] = 0
            _update_state["started_at"] = MarketService._state_now().isoformat()
            _update_state["completed_at"] = None
            _update_state["eta_seconds"] = None
            _update_state["elapsed_seconds"] = 0
            _update_state["resume_supported"] = True
            _update_state["initial_completed"] = 0
            _update_state["completed_in_run"] = 0
            _update_state["checkpoint_path"] = None
            _update_state["last_error"] = None
            _update_state["message"] = "准备更新..."
            return True

    @staticmethod
    def finish_update(message: str = "更新完成") -> None:
        """结束更新（成功）。"""
        with _update_lock:
            _update_state["status"] = "completed"
            _update_state["running"] = False
            _update_state["progress"] = 100
            _update_state["current"] = _update_state["total"]
            _update_state["eta_seconds"] = 0
            _update_state["completed_at"] = MarketService._state_now().isoformat()
            _update_state["elapsed_seconds"] = MarketService._elapsed_seconds_since(_update_state["started_at"])
            _update_state["message"] = message
            _update_state["last_error"] = None

    @staticmethod
    def fail_update(message: str) -> None:
        """结束更新（失败）。"""
        with _update_lock:
            _update_state["status"] = "failed"
            _update_state["running"] = False
            _update_state["eta_seconds"] = None
            _update_state["completed_at"] = MarketService._state_now().isoformat()
            _update_state["elapsed_seconds"] = MarketService._elapsed_seconds_since(_update_state["started_at"])
            _update_state["message"] = message
            _update_state["last_error"] = message

    @staticmethod
    def update_progress(payload: Dict[str, Any]) -> None:
        """更新进度。"""
        with _update_lock:
            elapsed_seconds = MarketService._elapsed_seconds_since(_update_state["started_at"])

            _update_state["status"] = "running"
            _update_state["running"] = True
            _update_state["task_type"] = str(payload.get("task_type") or _update_state["task_type"] or "incremental_update")
            _update_state["mode"] = str(payload.get("mode") or _update_state["mode"] or "per_stock")
            _update_state["target_trade_date"] = payload.get("target_trade_date", _update_state["target_trade_date"])
            _update_state["stage_label"] = payload.get("stage_label", _update_state["stage_label"])
            _update_state["current"] = int(payload.get("current", _update_state["current"]) or 0)
            _update_state["total"] = int(payload.get("total", _update_state["total"]) or 0)
            _update_state["progress"] = int(payload.get("progress", _update_state["progress"]) or 0)
            _update_state["current_code"] = payload.get("current_code")
            _update_state["updated_count"] = int(payload.get("updated_count", _update_state["updated_count"]) or 0)
            _update_state["skipped_count"] = int(payload.get("skipped_count", _update_state["skipped_count"]) or 0)
            _update_state["failed_count"] = int(payload.get("failed_count", _update_state["failed_count"]) or 0)
            _update_state["eta_seconds"] = payload.get("eta_seconds")
            _update_state["elapsed_seconds"] = int(payload.get("elapsed_seconds", elapsed_seconds) or 0)
            _update_state["resume_supported"] = bool(payload.get("resume_supported", True))
            _update_state["initial_completed"] = int(payload.get("initial_completed", _update_state["initial_completed"]) or 0)
            _update_state["completed_in_run"] = int(payload.get("completed_in_run", _update_state["completed_in_run"]) or 0)
            _update_state["checkpoint_path"] = payload.get("checkpoint_path", _update_state["checkpoint_path"])
            _update_state["message"] = str(payload.get("message") or _update_state["message"] or "增量更新进行中")

    @staticmethod
    def sync_update_state_from_task(task: Any) -> None:
        """从正式 Task 同步兼容的增量更新状态。

        供旧的 `/tasks/incremental-status` 和前端兼容视图使用。
        """
        if task is None:
            return

        params = dict(getattr(task, "params_json", None) or {})
        progress_meta = dict(getattr(task, "progress_meta_json", None) or {})
        result = dict(getattr(task, "result_json", None) or {})
        status = str(getattr(task, "status", "") or "idle")
        running = status in ("pending", "running")
        mode = str(progress_meta.get("mode") or result.get("mode") or "daily_batch")
        target_trade_date = (
            params.get("trade_date")
            or progress_meta.get("target_trade_date")
            or result.get("trade_date")
        )
        current = int(progress_meta.get("current") or (1 if status == "completed" else 0) or 0)
        total = int(progress_meta.get("total") or 1)
        progress = int(getattr(task, "progress", 0) or 0)
        updated_count = int(
            result.get("stock_count")
            or result.get("db_stock_count")
            or progress_meta.get("updated_count")
            or 0
        )
        failed_count = int(progress_meta.get("failed_count") or (1 if status == "failed" else 0) or 0)

        payload = {
            "status": status,
            "running": running,
            "task_id": getattr(task, "id", None),
            "task_type": str(getattr(task, "task_type", None) or "incremental_update"),
            "mode": mode,
            "target_trade_date": target_trade_date,
            "stage_label": progress_meta.get("stage_label") or "按交易日批量刷新",
            "progress": progress,
            "current": current,
            "total": total,
            "current_code": progress_meta.get("current_code") or target_trade_date,
            "updated_count": updated_count,
            "skipped_count": int(progress_meta.get("skipped_count") or 0),
            "failed_count": failed_count,
            "started_at": task.started_at.isoformat() if getattr(task, "started_at", None) else None,
            "completed_at": task.completed_at.isoformat() if getattr(task, "completed_at", None) else None,
            "eta_seconds": progress_meta.get("eta_seconds"),
            "elapsed_seconds": int(progress_meta.get("elapsed_seconds") or 0),
            "resume_supported": bool(progress_meta.get("resume_supported", False)),
            "initial_completed": int(progress_meta.get("initial_completed") or 0),
            "completed_in_run": int(progress_meta.get("completed_in_run") or current or 0),
            "checkpoint_path": progress_meta.get("checkpoint_path"),
            "last_error": getattr(task, "error_message", None),
            "message": str(
                progress_meta.get("message")
                or result.get("message")
                or getattr(task, "summary", "")
                or "增量更新任务"
            ),
        }

        with _update_lock:
            _update_state.update(payload)

    @property
    def pro(self):
        """获取 Tushare Pro 客户端"""
        if self._pro is None:
            if not self.token:
                raise ValueError("Tushare Token 未设置")
            import tushare as ts
            self._pro = ts.pro_api(self.token)
        return self._pro

    def _load_cache(self) -> dict:
        """加载缓存"""
        if MARKET_CACHE_FILE.exists():
            try:
                with open(MARKET_CACHE_FILE, "r") as f:
                    return json.load(f)
            except:
                pass
        return {"latest_trade_date": None, "updated_at": None}

    def _save_cache(self):
        """保存缓存"""
        MARKET_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MARKET_CACHE_FILE, "w") as f:
            json.dump(self._cache, f)

    def get_latest_trade_date(self) -> Optional[str]:
        """获取最新交易日

        Returns:
            最新交易日字符串 (YYYY-MM-DD)，如果获取失败返回 None
        """
        try:
            # 获取最近的交易日日历
            now = utc_now()
            today = now.strftime("%Y%m%d")
            start_date = (now - timedelta(days=10)).strftime("%Y%m%d")

            acquire_tushare_slot("trade_cal")
            df = self.pro.trade_cal(
                exchange="SSE",
                start_date=start_date,
                end_date=today
            )

            if df is not None and not df.empty:
                # 筛选交易日，倒序取第一个
                trade_days = df[df["is_open"] == 1].sort_values("cal_date", ascending=False)
                if not trade_days.empty:
                    latest_date = trade_days.iloc[0]["cal_date"]
                    # 转换为 YYYY-MM-DD 格式
                    return f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"

            return None
        except Exception as e:
            print(f"获取最新交易日失败: {e}")
            return None

    def get_cached_trade_date(self) -> Optional[str]:
        """获取缓存的最新交易日"""
        return self._cache.get("latest_trade_date")

    def should_update_data(self) -> tuple[bool, Optional[str]]:
        """判断是否需要更新数据

        Returns:
            (是否需要更新, 最新交易日日期)
        """
        latest_date = self.get_latest_trade_date()
        if not latest_date:
            return False, None

        cached_date = self.get_cached_trade_date()

        # 如果缓存为空，需要更新
        if not cached_date:
            return True, latest_date

        # 如果最新交易日更新，需要更新数据
        if latest_date > cached_date:
            return True, latest_date

        return False, latest_date

    def update_cache(self, latest_date: str):
        """更新缓存"""
        self._cache["latest_trade_date"] = latest_date
        self._cache["updated_at"] = utc_now().isoformat()
        self._save_cache()

    def get_local_latest_date(self) -> Optional[str]:
        """获取本地数据最新日期

        通过检查本地 CSV 文件获取最新交易日的日期
        """
        from app.config import settings
        raw_dir = ROOT / settings.raw_data_dir

        if not raw_dir.exists():
            return None

        latest_dates = []
        for csv_file in raw_dir.glob("*.csv"):
            try:
                df = pd.read_csv(csv_file)
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    latest = df["date"].max()
                    latest_dates.append(latest)
            except:
                pass

        if latest_dates:
            return max(latest_dates).strftime("%Y-%m-%d")

        return None

    def get_prepared_cache_path(self, trade_date: str) -> Path:
        """获取预处理数据的缓存路径"""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / f"{PREPARED_CACHE_PREFIX}_{trade_date.replace('-', '')}.pkl"

    def load_prepared_data(self, trade_date: str) -> Optional[Dict[str, Any]]:
        """加载预处理数据缓存

        Returns:
            包含 prepared, pool_codes, candidates 的字典，如果缓存不存在返回 None
        """
        cache_path = self.get_prepared_cache_path(trade_date)
        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"加载缓存失败: {e}")
        return None

    def save_prepared_data(self, trade_date: str, data: Dict[str, Any]):
        """保存预处理数据到缓存"""
        cache_path = self.get_prepared_cache_path(trade_date)
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(data, f)
            print(f"缓存已保存: {cache_path}")
        except Exception as e:
            print(f"保存缓存失败: {e}")

    def clear_old_cache(self, keep_days: int = 5):
        """清理旧的缓存文件，只保留最近几天的"""
        if not CACHE_DIR.exists():
            return

        cache_files = list(CACHE_DIR.glob(f"{PREPARED_CACHE_PREFIX}_*.pkl"))
        cache_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # 删除超过保留天数的缓存
        for old_file in cache_files[keep_days:]:
            try:
                old_file.unlink()
                print(f"已删除旧缓存: {old_file}")
            except Exception as e:
                print(f"删除缓存失败: {e}")

    def incremental_update(
        self,
        end_date: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """增量更新股票数据

        Args:
            end_date: 结束日期 (YYYY-MM-DD 或 YYYYMMDD)，默认为今天
            progress_callback: 进度回调函数 callback(current, total, code, status)

        Returns:
            更新结果汇总
        """
        end_date = self._normalize_end_date(end_date)

        batch_result = self._incremental_update_by_trade_date(
            end_date=end_date,
            progress_callback=progress_callback,
        )
        if batch_result.get("ok"):
            return batch_result

        logger.warning(
            "按交易日批量增量刷新失败，回退旧按股模式: %s",
            batch_result.get("message") or batch_result.get("error") or "unknown error",
        )
        return self._incremental_update_by_stock(
            end_date=end_date,
            progress_callback=progress_callback,
            fallback_reason=batch_result.get("message") or batch_result.get("error"),
        )

    def _incremental_update_by_trade_date(
        self,
        *,
        end_date: str,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        trade_date = self._display_trade_date(end_date)

        if progress_callback:
            progress_callback(
                {
                    "current": 0,
                    "total": 1,
                    "progress": 0,
                    "current_code": trade_date,
                    "target_trade_date": trade_date,
                    "task_type": "daily_batch_update",
                    "mode": "daily_batch",
                    "stage_label": "按交易日批量刷新",
                    "updated_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                    "eta_seconds": None,
                    "elapsed_seconds": 0,
                    "resume_supported": False,
                    "initial_completed": 0,
                    "completed_in_run": 0,
                    "checkpoint_path": None,
                    "message": f"按交易日批量刷新 {trade_date}",
                    "status": "starting",
                }
            )

        started_at = time.time()
        try:
            with DailyBatchUpdateService(token=self.token) as service:
                result = service.update_trade_date(trade_date, source="incremental_update")
        except Exception as exc:
            return {
                "ok": False,
                "success": False,
                "mode": "daily_batch",
                "trade_date": trade_date,
                "updated": 0,
                "skipped": 0,
                "failed": 1,
                "message": f"按交易日批量刷新失败: {exc}",
                "error": str(exc),
            }

        if not result.get("ok"):
            return {
                "ok": False,
                "success": False,
                "mode": "daily_batch",
                "trade_date": trade_date,
                "updated": 0,
                "skipped": 0,
                "failed": 1,
                "message": str(result.get("message") or f"{trade_date} 按交易日批量刷新失败"),
            }

        updated_count = int(result.get("stock_count") or result.get("db_stock_count") or 0)
        elapsed_seconds = max(0, int(time.time() - started_at))
        latest_trade = self.get_latest_trade_date()
        if latest_trade:
            self.update_cache(latest_trade)

        payload = {
            "current": 1,
            "total": 1,
            "progress": 100,
            "current_code": trade_date,
            "target_trade_date": trade_date,
            "task_type": "daily_batch_update",
            "mode": "daily_batch",
            "stage_label": "按交易日批量刷新",
            "updated_count": updated_count,
            "skipped_count": 0,
            "failed_count": 0,
            "eta_seconds": 0,
            "elapsed_seconds": elapsed_seconds,
            "resume_supported": False,
            "initial_completed": 0,
            "completed_in_run": 1,
            "checkpoint_path": None,
            "message": f"按交易日批量刷新完成 {trade_date}，写入 {updated_count} 只股票",
            "status": "completed",
        }
        if progress_callback:
            progress_callback(payload)

        return {
            "ok": True,
            "success": True,
            "mode": "daily_batch",
            "trade_date": trade_date,
            "total": 1,
            "completed": 1,
            "updated": updated_count,
            "skipped": 0,
            "failed": 0,
            "success_count": updated_count,
            "resume_supported": False,
            "checkpoint_path": None,
            "message": payload["message"],
            "record_count": int(result.get("record_count") or 0),
            "stock_count": updated_count,
        }

    def _incremental_update_by_stock(
        self,
        *,
        end_date: str,
        progress_callback: Optional[Callable] = None,
        fallback_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app.config import settings
        from pipeline.fetch_kline import fetch_one_incremental

        stocklist_path = ROOT / "pipeline" / "stocklist.csv"
        if not stocklist_path.exists():
            return {"success": False, "error": "股票列表文件不存在"}

        df = pd.read_csv(stocklist_path)
        codes = df["symbol"].astype(str).str.zfill(6).tolist()

        raw_dir = ROOT / settings.raw_data_dir
        raw_dir.mkdir(parents=True, exist_ok=True)

        token = os.environ.get("TUSHARE_TOKEN") or self.token
        if not token:
            return {"success": False, "error": "Tushare Token 未设置"}

        db_url = settings.database_url
        workers = 8

        results = {
            "ok": False,
            "total": len(codes),
            "success": 0,
            "failed": 0,
            "updated": 0,
            "skipped": 0,
            "resume_supported": True,
            "mode": "per_stock_fallback",
            "fallback_reason": fallback_reason,
        }
        checkpoint_path = self._build_incremental_checkpoint_path(codes, end_date, raw_dir)
        checkpoint = self._load_incremental_checkpoint(checkpoint_path)
        completed_codes, failed_codes = self._restore_incremental_checkpoint(checkpoint, codes)
        initial_completed = len(completed_codes)
        remaining_codes = [code for code in codes if code not in completed_codes]
        results["initial_completed"] = initial_completed
        results["checkpoint_path"] = str(checkpoint_path)

        self._save_incremental_checkpoint(
            checkpoint_path,
            codes=codes,
            end_date=end_date,
            raw_dir=raw_dir,
            completed_codes=completed_codes,
            failed_codes=failed_codes,
        )

        def update_single_code(code: str) -> dict:
            try:
                result = fetch_one_incremental(
                    code,
                    end_date,
                    raw_dir,
                    db_url=db_url,
                )
            except Exception as e:
                result = {
                    "code": code,
                    "success": False,
                    "updated": False,
                    "new_count": 0,
                    "error": str(e),
                }
            return result

        run_started_at = time.time()
        completed_in_run = 0
        failed_in_run = 0

        def emit_progress(current_code: Optional[str], status: str) -> None:
            nonlocal completed_in_run, failed_in_run
            current = len(completed_codes)
            total = len(codes)
            processed_in_run = completed_in_run + failed_in_run
            elapsed_seconds = max(0, int(time.time() - run_started_at))
            remaining = max(0, len(remaining_codes) - processed_in_run)
            eta_seconds: Optional[int] = None
            if processed_in_run > 0 and remaining > 0 and elapsed_seconds > 0:
                eta_seconds = max(0, int((elapsed_seconds / processed_in_run) * remaining))
            elif remaining == 0:
                eta_seconds = 0

            message = (
                f"增量更新 {current}/{total}"
                + (f" | 当前 {current_code}" if current_code else "")
                + (f" | 预计剩余 {eta_seconds} 秒" if eta_seconds is not None and eta_seconds > 0 else "")
            )
            if fallback_reason and status == "starting":
                message += f" | 已回退按股模式: {fallback_reason}"

            payload = {
                "current": current,
                "total": total,
                "progress": int(current / total * 100) if total > 0 else 0,
                "current_code": current_code,
                "updated_count": results["updated"],
                "skipped_count": results["skipped"],
                "failed_count": len(failed_codes),
                "eta_seconds": eta_seconds,
                "elapsed_seconds": elapsed_seconds,
                "resume_supported": True,
                "initial_completed": initial_completed,
                "completed_in_run": completed_in_run,
                "checkpoint_path": str(checkpoint_path),
                "message": message,
                "status": status,
            }
            if progress_callback:
                progress_callback(payload)

        emit_progress(None, "starting")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(update_single_code, code): code
                for code in remaining_codes
            }
            for future in as_completed(futures):
                code = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {"code": code, "success": False, "updated": False, "error": str(e)}

                if result["success"]:
                    completed_codes.add(code)
                    completed_in_run += 1
                    results["success"] += 1
                    failed_codes.pop(code, None)
                    if result["updated"]:
                        results["updated"] += 1
                        status = "updated"
                    else:
                        results["skipped"] += 1
                        status = "skipped"
                else:
                    failed_in_run += 1
                    results["failed"] += 1
                    failed_codes[code] = str(result.get("error") or "更新失败")
                    status = "failed"

                self._save_incremental_checkpoint(
                    checkpoint_path,
                    codes=codes,
                    end_date=end_date,
                    raw_dir=raw_dir,
                    completed_codes=completed_codes,
                    failed_codes=failed_codes,
                )
                emit_progress(code, status)

        if not remaining_codes:
            emit_progress(None, "completed")

        results["completed"] = len(completed_codes)
        results["failed"] = len(failed_codes)
        results["ok"] = len(failed_codes) == 0

        if results["ok"]:
            latest_trade = self.get_latest_trade_date()
            if latest_trade:
                self.update_cache(latest_trade)
            self._clear_incremental_checkpoint(checkpoint_path)

        return results


# 全局实例
market_service = MarketService()
