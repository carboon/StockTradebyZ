"""
Market Service
~~~~~~~~~~~~~~~
市场数据服务：获取最新交易日，判断数据是否需要更新，增量更新
"""
import json
import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable

import pandas as pd
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).parent.parent.parent.parent
CACHE_DIR = ROOT / "data" / "cache"
MARKET_CACHE_FILE = ROOT / "data" / ".market_cache.json"
PREPARED_CACHE_PREFIX = "prepared_data"

# 全局更新状态
_update_state = {
    "running": False,
    "task_id": None,
    "progress": 0,
    "total": 0,
    "current_code": None,
    "updated_count": 0,
    "skipped_count": 0,
    "failed_count": 0,
    "started_at": None,
    "message": "",
}


class MarketService:
    """市场数据服务"""

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
        return _update_state.copy()

    @staticmethod
    def start_update(task_id: Optional[int] = None) -> bool:
        """开始更新，返回是否成功（如果已有任务在运行则返回 False）"""
        global _update_state
        if _update_state["running"]:
            return False
        _update_state["running"] = True
        _update_state["task_id"] = task_id
        _update_state["progress"] = 0
        _update_state["total"] = 0
        _update_state["current_code"] = None
        _update_state["updated_count"] = 0
        _update_state["skipped_count"] = 0
        _update_state["failed_count"] = 0
        _update_state["started_at"] = datetime.now().isoformat()
        _update_state["message"] = "准备更新..."
        return True

    @staticmethod
    def finish_update():
        """结束更新"""
        global _update_state
        _update_state["running"] = False
        _update_state["progress"] = 100
        _update_state["message"] = "更新完成"

    @staticmethod
    def update_progress(current: int, total: int, code: str, status: str):
        """更新进度"""
        global _update_state
        _update_state["progress"] = int(current / total * 100) if total > 0 else 0
        _update_state["current_code"] = code
        _update_state["total"] = total
        if status == "updated":
            _update_state["updated_count"] += 1
        elif status == "skipped":
            _update_state["skipped_count"] += 1
        elif status == "failed":
            _update_state["failed_count"] += 1

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
            today = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

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
        self._cache["updated_at"] = datetime.now().isoformat()
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
        import sys
        import subprocess
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 解析结束日期
        if end_date:
            if "-" in end_date:
                end_date = end_date.replace("-", "")
        else:
            end_date = datetime.now().strftime("%Y%m%d")

        # 获取股票列表
        import pandas as pd
        stocklist_path = ROOT / "pipeline" / "stocklist.csv"
        if not stocklist_path.exists():
            return {"success": False, "error": "股票列表文件不存在"}

        df = pd.read_csv(stocklist_path)
        codes = df["symbol"].astype(str).str.zfill(6).tolist()

        # 输出目录
        from app.config import settings
        raw_dir = ROOT / settings.raw_data_dir
        raw_dir.mkdir(parents=True, exist_ok=True)

        # 获取 token
        token = os.environ.get("TUSHARE_TOKEN") or self.token
        if not token:
            return {"success": False, "error": "Tushare Token 未设置"}

        # 使用子进程调用 pipeline 的增量更新功能
        workers = 8

        results = {
            "total": len(codes),
            "success": 0,
            "failed": 0,
            "updated": 0,
            "skipped": 0,
        }

        def _get_latest_date_from_csv(csv_path: Path) -> Optional[str]:
            try:
                df = pd.read_csv(csv_path)
                if "date" in df.columns and not df.empty:
                    df["date"] = pd.to_datetime(df["date"])
                    latest = df["date"].max()
                    return latest.strftime("%Y%m%d")
            except Exception:
                pass
            return None

        def update_single_code(code: str) -> dict:
            csv_path = raw_dir / f"{code}.csv"
            result = {
                "code": code,
                "success": False,
                "updated": False,
                "new_count": 0,
            }

            latest_date = _get_latest_date_from_csv(csv_path)
            if latest_date:
                import datetime as dt
                latest_dt = dt.datetime.strptime(latest_date, "%Y%m%d")
                next_day = latest_dt + dt.timedelta(days=1)
                start_date = next_day.strftime("%Y%m%d")
            else:
                start_date = "20190101"

            if start_date >= end_date:
                result["success"] = True
                result["updated"] = False
                return result

            try:
                import tushare as ts
                pro = ts.pro_api(token)

                def _to_ts_code(c: str) -> str:
                    c = str(c).zfill(6)
                    if c.startswith(("60", "68", "9")):
                        return f"{c}.SH"
                    elif c.startswith(("4", "8")):
                        return f"{c}.BJ"
                    else:
                        return f"{c}.SZ"

                ts_code = _to_ts_code(code)
                from app.utils.tushare_rate_limit import acquire_tushare_slot
                acquire_tushare_slot("pro_bar")
                df = ts.pro_bar(
                    ts_code=ts_code,
                    adj="qfq",
                    start_date=start_date,
                    end_date=end_date,
                    freq="D",
                )

                if df is None or df.empty:
                    result["success"] = True
                    result["updated"] = False
                    return result

                df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
                    ["date", "open", "close", "high", "low", "volume"]
                ].copy()
                df["date"] = pd.to_datetime(df["date"])
                for c in ["open", "close", "high", "low", "volume"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df = df.sort_values("date").reset_index(drop=True)

                if latest_date and csv_path.exists():
                    old_df = pd.read_csv(csv_path)
                    old_df["date"] = pd.to_datetime(old_df["date"])
                    combined_df = pd.concat([old_df, df], ignore_index=True)
                    combined_df = combined_df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
                    result["new_count"] = len(df)
                else:
                    combined_df = df
                    result["new_count"] = len(df)

                combined_df.to_csv(csv_path, index=False)
                result["success"] = True
                result["updated"] = True
            except Exception as e:
                result["error"] = str(e)

            return result

        def update_wrapper(code: str, index: int):
            result = update_single_code(code)
            if result["success"]:
                results["success"] += 1
                if result["updated"]:
                    results["updated"] += 1
                    status = "updated"
                else:
                    results["skipped"] += 1
                    status = "skipped"
            else:
                results["failed"] += 1
                status = "failed"

            if progress_callback:
                progress_callback(index + 1, len(codes), code, status)

            return result

        # 多线程更新
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(update_wrapper, code, i): code
                for i, code in enumerate(codes)
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"增量更新异常: {e}")

        # 更新缓存
        latest_trade = self.get_latest_trade_date()
        if latest_trade:
            self.update_cache(latest_trade)

        results["success"] = True
        return results


# 全局实例
market_service = MarketService()
