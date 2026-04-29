"""
Tushare Data Service
~~~~~~~~~~~~~~~~~~~~
Tushare 数据服务
"""
import os
import pandas as pd
from pathlib import Path
from typing import Optional, List
import subprocess
import sys
import time
from sqlalchemy.orm import Session
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).parent.parent.parent.parent


class TushareService:
    """Tushare 数据服务"""
    _verify_cache: dict[str, tuple[float, tuple[bool, str]]] = {}
    _stock_list_cache: dict[str, tuple[float, pd.DataFrame]] = {}
    _latest_data_ready_cache: dict[str, tuple[float, bool]] = {}

    def __init__(self, token: Optional[str] = None):
        if token is not None:
            self.token = token
        else:
            from app.config import settings
            self.token = os.environ.get("TUSHARE_TOKEN", "") or settings.tushare_token
        self._pro = None

    @property
    def pro(self):
        """获取 Tushare Pro 客户端"""
        if self._pro is None:
            if not self.token:
                raise ValueError("Tushare Token 未设置")
            import tushare as ts
            self._pro = ts.pro_api(self.token)
        return self._pro

    def verify_token(self) -> tuple[bool, str]:
        """验证 Token 是否有效"""
        cache_key = self.token or ""
        cached = self._verify_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < 60:
            return cached[1]

        try:
            acquire_tushare_slot("daily")
            df = self.pro.daily(ts_code="000001.SZ", limit=1)
            if df is not None and not df.empty:
                result = (True, "Token 验证成功")
            else:
                result = (False, "Token 无效")
        except Exception as e:
            result = (False, f"验证失败: {str(e)}")

        self._verify_cache[cache_key] = (now, result)
        return result

    def get_stock_list(self) -> pd.DataFrame:
        """获取股票列表"""
        cache_key = self.token or ""
        cached = self._stock_list_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < 3600:
            return cached[1]

        acquire_tushare_slot("stock_basic")
        df = self.pro.stock_basic(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,area,industry,market'
        )
        self._stock_list_cache[cache_key] = (now, df)
        return df

    @staticmethod
    def _to_exchange(ts_code: str) -> Optional[str]:
        text = str(ts_code or "").upper()
        if text.endswith(".SH"):
            return "SH"
        if text.endswith(".SZ"):
            return "SZ"
        if text.endswith(".BJ"):
            return "BJ"
        return None

    def find_stock_by_code(self, code: str) -> Optional[dict]:
        """通过6位代码查找股票基础信息"""
        code = str(code).zfill(6)
        df = self.get_stock_list()
        if df is None or df.empty or "symbol" not in df.columns:
            return None

        matched = df[df["symbol"].astype(str).str.zfill(6) == code]
        if matched.empty:
            return None

        row = matched.iloc[0]
        return {
            "code": code,
            "name": row.get("name"),
            "market": self._to_exchange(row.get("ts_code", "")),
            "industry": row.get("industry"),
        }

    def sync_stock_to_db(self, db: Session, code: str) -> Optional[object]:
        """同步单只股票基础信息到数据库"""
        from app.models import Stock

        info = self.find_stock_by_code(code)
        if not info:
            return None

        stock = db.query(Stock).filter(Stock.code == info["code"]).first()
        if stock is None:
            stock = Stock(code=info["code"])
            db.add(stock)

        stock.name = info.get("name")
        stock.market = info.get("market")
        stock.industry = info.get("industry")
        db.commit()
        db.refresh(stock)
        return stock

    def sync_stock_list_to_db(self, db: Session) -> int:
        """全量同步股票基础信息到数据库"""
        from app.models import Stock

        df = self.get_stock_list()
        if df is None or df.empty:
            return 0

        existing = {
            stock.code: stock
            for stock in db.query(Stock).all()
        }
        synced = 0

        for _, row in df.iterrows():
            code = str(row.get("symbol", "")).zfill(6)
            if not code or code == "000000":
                continue

            stock = existing.get(code)
            if stock is None:
                stock = Stock(code=code)
                db.add(stock)
                existing[code] = stock

            stock.name = row.get("name")
            stock.market = self._to_exchange(row.get("ts_code", ""))
            stock.industry = row.get("industry")
            synced += 1

        db.commit()
        return synced

    def sync_stock_names_to_db(self, db: Session, codes: List[str]) -> int:
        """按代码批量补齐股票名称。"""
        from app.models import Stock

        normalized_codes = {
            str(code).zfill(6)
            for code in codes
            if str(code or "").strip()
        }
        if not normalized_codes:
            return 0

        df = self.get_stock_list()
        if df is None or df.empty:
            return 0

        lookup = df.copy()
        lookup["symbol"] = lookup["symbol"].astype(str).str.zfill(6)
        matched = lookup[lookup["symbol"].isin(normalized_codes)]
        if matched.empty:
            return 0

        existing = {
            stock.code: stock
            for stock in db.query(Stock).filter(Stock.code.in_(list(normalized_codes))).all()
        }

        synced = 0
        for _, row in matched.iterrows():
            code = str(row.get("symbol", "")).zfill(6)
            if not code or code == "000000":
                continue

            stock = existing.get(code)
            if stock is None:
                stock = Stock(code=code)
                db.add(stock)
                existing[code] = stock

            stock.name = row.get("name")
            stock.market = self._to_exchange(row.get("ts_code", ""))
            stock.industry = row.get("industry")
            synced += 1

        if synced:
            db.commit()
        return synced

    def get_daily_data(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取日线数据"""
        acquire_tushare_slot("daily")
        return self.pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )

    def is_trade_date_data_ready(
        self,
        trade_date: str,
        *,
        ts_code: str = "000001.SZ",
        ttl_seconds: int = 300,
    ) -> bool:
        """探测指定交易日的数据是否已在 Tushare 可读。"""
        normalized = str(trade_date or "").replace("-", "")
        if len(normalized) != 8 or not normalized.isdigit():
            return False

        cache_key = f"{self.token or ''}:{ts_code}:{normalized}"
        cached = self._latest_data_ready_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < ttl_seconds:
            return cached[1]

        ready = False
        try:
            acquire_tushare_slot("daily")
            df = self.pro.daily(ts_code=ts_code, start_date=normalized, end_date=normalized)
            ready = bool(df is not None and not df.empty)
        except Exception:
            ready = False

        self._latest_data_ready_cache[cache_key] = (now, ready)
        return ready

    def get_raw_data_path(self, code: str) -> Path:
        """获取原始数据文件路径"""
        from app.config import settings
        raw_dir = ROOT / settings.raw_data_dir
        return raw_dir / f"{code}.csv"

    def load_stock_data(self, code: str) -> Optional[pd.DataFrame]:
        """从本地加载股票数据"""
        csv_path = self.get_raw_data_path(code)
        if not csv_path.exists():
            return None
        df = pd.read_csv(csv_path)
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def check_data_status(self) -> dict:
        """检查数据状态"""
        from app.config import settings
        import json
        from datetime import datetime

        data_dir = ROOT / settings.data_dir
        status = {
            "raw_data": {"exists": False, "count": 0, "latest_date": None},
            "candidates": {"exists": False, "count": 0, "latest_date": None},
            "analysis": {"exists": False, "count": 0, "latest_date": None},
            "kline": {"exists": False, "count": 0, "latest_date": None},
        }

        # 检查原始数据
        raw_dir = data_dir / "raw"
        if raw_dir.exists():
            csv_files = list(raw_dir.glob("*.csv"))
            status["raw_data"]["exists"] = len(csv_files) > 0
            status["raw_data"]["count"] = len(csv_files)
            if csv_files:
                status["raw_data"]["latest_date"] = max(f.stat().st_mtime for f in csv_files)

        # 检查候选数据
        candidates_file = data_dir / "candidates" / "candidates_latest.json"
        if candidates_file.exists():
            try:
                with open(candidates_file, "r") as f:
                    data = json.load(f)
                    status["candidates"]["exists"] = True
                    status["candidates"]["latest_date"] = data.get("pick_date")
            except:
                pass

        # 检查分析数据
        review_dir = data_dir / "review"
        if review_dir.exists():
            date_dirs = [d for d in review_dir.iterdir() if d.is_dir()]
            status["analysis"]["exists"] = len(date_dirs) > 0
            status["analysis"]["count"] = len(date_dirs)
            if date_dirs:
                status["analysis"]["latest_date"] = max(d.name for d in date_dirs)

        # 检查K线图
        kline_dir = data_dir / "kline"
        if kline_dir.exists():
            jpg_files = list(kline_dir.rglob("*.jpg"))
            status["kline"]["exists"] = len(jpg_files) > 0
            status["kline"]["count"] = len(jpg_files)

        return status
