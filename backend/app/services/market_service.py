"""
Market Service
~~~~~~~~~~~~~~~
市场数据服务：获取最新交易日，判断数据是否需要更新，管理同步状态
"""
import json
import os
import pickle
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).parent.parent.parent.parent
CACHE_DIR = ROOT / "data" / "cache"
MARKET_CACHE_FILE = ROOT / "data" / ".market_cache.json"
UPDATE_STATUS_FILE = ROOT / "data" / ".update_status.json"
PREPARED_CACHE_PREFIX = "prepared_data"


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
        self._ensure_status_file()

    @property
    def pro(self):
        """获取 Tushare Pro 客户端"""
        if self._pro is None:
            if not self.token:
                raise ValueError("Tushare Token 未设置")
            import tushare as ts
            ts.set_token(self.token)
            self._pro = ts.pro_api()
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

    def _ensure_status_file(self):
        """确保更新状态文件存在"""
        if not UPDATE_STATUS_FILE.exists():
            UPDATE_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._save_status({
                "last_check_time": 0, 
                "last_trade_date": None, 
                "is_updating": False,
                "update_type": None, # 'full' or 'incremental'
                "progress": {"current": 0, "total": 0},
                "message": ""
            })

    def _load_status(self) -> dict:
        """加载更新状态"""
        try:
            with open(UPDATE_STATUS_FILE, "r") as f:
                return json.load(f)
        except:
            return {"last_check_time": 0, "last_trade_date": None, "is_updating": False}

    def _save_status(self, status: dict):
        """保存更新状态"""
        with open(UPDATE_STATUS_FILE, "w") as f:
            json.dump(status, f)

    def get_latest_trade_date(self) -> Optional[str]:
        """获取最新交易日

        Returns:
            最新交易日字符串 (YYYY-MM-DD)，如果获取失败返回 None
        """
        try:
            # 每次调用时重新检查 Token，确保使用最新的配置
            from app.config import settings
            current_token = os.environ.get("TUSHARE_TOKEN", "") or settings.tushare_token
            if not current_token or current_token == "your_tushare_token_here":
                print("Warning: TUSHARE_TOKEN not configured")
                return None
            
            # 如果当前实例的 token 与配置不一致，重新初始化 pro 客户端
            if self.token != current_token:
                self.token = current_token
                self._pro = None  # 重置 pro 客户端

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

    def get_network_time_beijing(self) -> datetime:
        """
        获取北京时间（网络时间），解决本地系统时间不准的问题。
        优先使用 Tushare 服务器响应头，备选阿里云 NTP。
        """
        try:
            # 方法1: 尝试从 Tushare 官网获取时间
            resp = requests.head("https://tushare.pro", timeout=2)
            date_str = resp.headers.get('Date')
            if date_str:
                from email.utils import parsedate_to_datetime
                utc_dt = parsedate_to_datetime(date_str)
                return utc_dt + timedelta(hours=8)
        except:
            pass
        
        # 方法2: 备选阿里云时间接口
        try:
            resp = requests.get("http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp", timeout=2)
            ts = int(resp.json()['data']['t']) / 1000
            return datetime.fromtimestamp(ts)
        except:
            # 极端情况下回退到本地时间
            print("Warning: Failed to fetch network time, using local system time.")
            return datetime.now()

    def get_sync_status(self) -> dict:
        """获取当前数据同步状态供前端展示"""
        status = self._load_status()
        # 直接从 Tushare 获取最新交易日，不依赖缓存
        remote_date = self.get_latest_trade_date()
        
        # 计算进度百分比
        progress_pct = 0
        if status.get("is_updating") and status.get("progress", {}).get("total", 0) > 0:
            current = status["progress"].get("current", 0)
            total = status["progress"].get("total", 0)
            progress_pct = int((current / total) * 100)

        return {
            "local_last_date": status.get("last_trade_date"),
            "remote_latest_date": remote_date,
            "is_synced": status.get("last_trade_date") == remote_date and not status.get("is_updating"),
            "is_updating": status.get("is_updating", False),
            "update_type": status.get("update_type"), # 'full', 'incremental', or None
            "progress_pct": progress_pct,
            "progress_detail": status.get("progress", {}),
            "message": status.get("message", ""),
            "server_time": self.get_network_time_beijing().strftime("%Y-%m-%d %H:%M:%S")
        }

    def check_and_trigger_update(self) -> dict:
        """
        前端调用此接口。它不会立即执行更新，而是判断是否需要提交后台任务。
        """
        status = self._load_status()
        now_beijing = self.get_network_time_beijing()
        
        # 1. 如果正在更新中，直接返回忙碌状态
        if status.get("is_updating"):
            return {"action": "wait", "message": "后台数据更新进行中..."}

        # 2. 频率限制：如果距离上次检查不到 5 分钟，直接返回缓存结果
        if now_beijing.timestamp() - status.get("last_check_time", 0) < 300:
            return {
                "action": "none", 
                "local_date": status.get("last_trade_date"),
                "message": "数据状态已缓存"
            }

        # 3. 提交后台异步任务去执行真正的逻辑
        from app.services.task_service import trigger_data_sync_task
        trigger_data_sync_task()
        
        # 更新检查时间
        status["last_check_time"] = now_beijing.timestamp()
        status["is_updating"] = True
        self._save_status(status)
        
        return {"action": "started", "message": "已启动后台数据同步"}

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


# 全局实例
market_service = MarketService()
