"""
Tushare Data Service
~~~~~~~~~~~~~~~~~~~~
Tushare 数据服务
"""
import os
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).parent.parent.parent.parent


class TushareService:
    """Tushare 数据服务"""
    _verify_cache: dict[str, tuple[float, tuple[bool, str]]] = {}
    _stock_list_cache: dict[str, tuple[float, pd.DataFrame]] = {}
    _latest_data_ready_cache: dict[str, tuple[float, bool]] = {}
    # check_data_status 缓存（非实时系统，使用较长缓存时间）
    _data_status_cache: dict[str, tuple[float, dict]] = {}
    _data_status_cache_ttl = 300  # 5分钟缓存 - 数据只有在交易完成后才会更新

    def __init__(self, token: Optional[str] = None):
        if token is not None:
            self.token = token
        else:
            from app.config import settings
            env_token = os.environ.get("TUSHARE_TOKEN", "")
            self.token = env_token if env_token else ""
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
        if self._pro is None:
            self._verify_cache.pop(cache_key, None)
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
        if self._pro is None:
            self._stock_list_cache.pop(cache_key, None)
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

    def warm_stock_list_cache(self) -> bool:
        """预热股票列表缓存，失败时吞掉异常并返回 False。"""
        try:
            df = self.get_stock_list()
            return df is not None and not df.empty
        except Exception:
            return False

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

    def get_latest_trade_date(self) -> Optional[str]:
        """获取最近一个交易日；失败时返回 None。"""
        if not self.token:
            return None

        try:
            acquire_tushare_slot("trade_cal")
            today = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            df = self.pro.trade_cal(exchange="SSE", start_date=start_date, end_date=today)
            if df is None or df.empty:
                return None

            trade_days = df[df["is_open"] == 1].sort_values("cal_date", ascending=False)
            if trade_days.empty:
                return None

            latest = str(trade_days.iloc[0]["cal_date"])
            return f"{latest[:4]}-{latest[4:6]}-{latest[6:]}"
        except Exception:
            return None

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

    def get_effective_latest_trade_date(self) -> Optional[str]:
        """获取用于判断“是否过期”的有效最新交易日。

        规则：
        - 北京时间 17:00 前，不把当日直接视为应完成同步的目标日；
        - 17:00 后，如果当天数据在 Tushare 已可读，则目标日为当天；
        - 否则回退到上一个开市日。
        """
        latest_trade_date = self.get_latest_trade_date()
        if not latest_trade_date:
            return None

        try:
            bj_now = datetime.now(ZoneInfo("Asia/Shanghai"))
            latest_dt = datetime.fromisoformat(latest_trade_date).date()

            if latest_dt < bj_now.date():
                return latest_trade_date

            if bj_now.hour < 17:
                acquire_tushare_slot("trade_cal")
                start_date = (bj_now - timedelta(days=10)).strftime("%Y%m%d")
                end_date = bj_now.strftime("%Y%m%d")
                df = self.pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date)
                if df is None or df.empty:
                    return latest_trade_date
                trade_days = df[df["is_open"] == 1].sort_values("cal_date", ascending=False)
                previous_days = [
                    f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}"
                    for day in trade_days["cal_date"].tolist()
                    if f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}" < latest_trade_date
                ]
                return previous_days[0] if previous_days else latest_trade_date

            if self.is_trade_date_data_ready(latest_trade_date):
                return latest_trade_date

            acquire_tushare_slot("trade_cal")
            start_date = (bj_now - timedelta(days=10)).strftime("%Y%m%d")
            end_date = bj_now.strftime("%Y%m%d")
            df = self.pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return latest_trade_date
            trade_days = df[df["is_open"] == 1].sort_values("cal_date", ascending=False)
            previous_days = [
                f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}"
                for day in trade_days["cal_date"].tolist()
                if f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}" < latest_trade_date
            ]
            return previous_days[0] if previous_days else latest_trade_date
        except Exception:
            return latest_trade_date

    def get_suspended_stocks(self, trade_date: str) -> set[str]:
        """获取指定日期的停牌股票代码集合

        Args:
            trade_date: 交易日期，格式 YYYY-MM-DD

        Returns:
            停牌股票代码集合（6位代码）
        """
        if not self.token or not trade_date:
            return set()

        try:
            from app.utils.stock_metadata import resolve_ts_code
            import tushare as ts

            # 转换日期格式 YYYY-MM-DD -> YYYYMMDD
            date_yyyymmdd = trade_date.replace("-", "")

            # 获取停牌信息
            acquire_tushare_slot("suspend")
            df = self.pro.suspend(
                suspend_date=date_yyyymmdd,
                fields="ts_code,suspend_date,suspend_reason"
            )

            if df is None or df.empty:
                return set()

            # 提取停牌股票的6位代码
            # 注意：suspend 接口返回的所有记录都是停牌股票，不需要检查 is_suspended 字段
            suspended_codes = set()
            for _, row in df.iterrows():
                ts_code = row.get("ts_code", "")
                if ts_code:
                    # 从 ts_code (如 000001.SZ) 提取6位代码
                    code = ts_code.split(".")[0] if "." in ts_code else ts_code
                    if len(code) == 6:
                        suspended_codes.add(code)

            return suspended_codes
        except Exception as e:
            # 获取停牌信息失败不影响主流程，返回空集
            import logging
            logging.getLogger("tushare_service").warning(f"获取停牌信息失败: {e}")
            return set()

    def get_raw_data_path(self, code: str) -> Path:
        """获取原始数据文件路径（已弃用，保留用于兼容）"""
        from app.config import settings
        raw_dir = ROOT / settings.raw_data_dir
        return raw_dir / f"{code}.csv"

    def load_stock_data(self, code: str) -> Optional[pd.DataFrame]:
        """优先从数据库加载股票数据，失败时回退 CSV 文件。"""
        from app.services.kline_service import get_daily_data
        from app.database import SessionLocal
        from datetime import timedelta

        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=365)

        try:
            with SessionLocal() as db:
                df = get_daily_data(db, code, start_date, end_date)
        except SQLAlchemyError:
            df = None

        if df is None or df.empty:
            csv_path = self.get_raw_data_path(code)
            if not csv_path.exists():
                return None
            df = pd.read_csv(csv_path)

        df.columns = [c.lower() for c in df.columns]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        else:
            return None

        return df.sort_values("date").reset_index(drop=True)

    def check_data_status(self) -> dict:
        """检查数据状态，优先数据库，失败时回退本地文件系统。"""
        # 检查缓存
        now = time.time()
        cache_key = "data_status"
        if self._pro is None:
            self._data_status_cache.pop(cache_key, None)
        cached = self._data_status_cache.get(cache_key)
        if cached and now - cached[0] < self._data_status_cache_ttl:
            return cached[1]

        from app.config import settings
        from app.database import SessionLocal
        from app.models import StockDaily, Candidate, AnalysisResult
        from sqlalchemy import func, select, distinct
        import json

        latest_trade_date = self.get_effective_latest_trade_date()
        calendar_latest_trade_date = self.get_latest_trade_date()

        # 获取预期的股票总数（从 stocklist.csv）
        from backend.app.api.tasks import _load_expected_fetch_codes
        expected_codes = _load_expected_fetch_codes()
        expected_total = len(expected_codes)

        status = {
            "raw_data": {
                "exists": False,
                "count": 0,
                "stock_count": 0,
                "raw_record_count": 0,
                "latest_date": None,
                "latest_trade_date": latest_trade_date,
                "calendar_latest_trade_date": calendar_latest_trade_date,
                "is_latest": False,
                "latest_date_stock_count": 0,
                "expected_stock_count": expected_total,
                "is_latest_complete": False,
            },
            "candidates": {"exists": False, "count": 0, "latest_date": None},
            "analysis": {"exists": False, "count": 0, "latest_date": None},
            "kline": {"exists": False, "count": 0, "latest_date": None},
        }

        try:
            with SessionLocal() as db:
                # 检查 K线数据（数据库）
                kline_count = db.execute(select(func.count()).select_from(StockDaily)).scalar()
                if kline_count and kline_count > 0:
                    status["raw_data"]["exists"] = True
                    status["raw_data"]["raw_record_count"] = kline_count

                    # 获取最新日期
                    latest = db.execute(
                        select(StockDaily.trade_date)
                        .order_by(StockDaily.trade_date.desc())
                        .limit(1)
                    ).first()
                    if latest:
                        latest_local_date = latest[0].isoformat() if hasattr(latest[0], "isoformat") else str(latest[0])
                        status["raw_data"]["latest_date"] = latest_local_date
                        latest_day_stock_count = db.execute(
                            select(func.count(distinct(StockDaily.code)))
                            .where(StockDaily.trade_date == latest[0])
                        ).scalar() or 0
                        status["raw_data"]["latest_date_stock_count"] = latest_day_stock_count

                    # 获取有数据的股票数
                    stocks_with_data = db.execute(
                        select(func.count(distinct(StockDaily.code)))
                    ).scalar()
                    if stocks_with_data:
                        status["raw_data"]["stock_count"] = stocks_with_data
                        status["raw_data"]["count"] = stocks_with_data
                        status["kline"]["exists"] = True
                        status["kline"]["count"] = stocks_with_data

                    # 获取停牌股票信息（从预期总数中排除）
                    suspended_codes = self.get_suspended_stocks(latest_trade_date) if latest_trade_date else set()

                    # 额外获取"长期无数据"的股票（可能是长期停牌或退市）
                    from datetime import timedelta
                    long_stale_codes = set()

                    if latest_trade_date and latest:
                        try:
                            from datetime import datetime
                            latest_dt = datetime.fromisoformat(latest_trade_date) if isinstance(latest_trade_date, str) else latest_trade_date
                            stale_threshold = latest_dt - timedelta(days=1)

                            stale_result = db.execute(
                                select(StockDaily.code)
                                .group_by(StockDaily.code)
                                .having(func.max(StockDaily.trade_date) < stale_threshold.date())
                            ).all()

                            long_stale_codes = {row[0] for row in stale_result}
                        except Exception as e:
                            import logging
                            logging.getLogger("tushare_service").warning(f"获取长期停牌股票失败: {e}")

                    all_excluded_codes = suspended_codes | long_stale_codes
                    active_expected_count = expected_total - len(all_excluded_codes)

                    status["raw_data"]["is_latest"] = bool(
                        status["raw_data"]["latest_date"] and latest_trade_date
                        and status["raw_data"]["latest_date"] == latest_trade_date
                    )
                    status["raw_data"]["is_latest_complete"] = bool(
                        status["raw_data"]["is_latest"]
                        and active_expected_count > 0
                        and status["raw_data"]["latest_date_stock_count"] >= active_expected_count
                    )

                candidate_count = db.execute(select(func.count()).select_from(Candidate)).scalar() or 0
                if candidate_count > 0:
                    status["candidates"]["exists"] = True
                    status["candidates"]["count"] = candidate_count
                    latest_candidate = db.execute(
                        select(Candidate.pick_date)
                        .order_by(Candidate.pick_date.desc())
                        .limit(1)
                    ).first()
                    if latest_candidate:
                        status["candidates"]["latest_date"] = latest_candidate[0].isoformat()

                analysis_count = db.execute(select(func.count()).select_from(AnalysisResult)).scalar() or 0
                if analysis_count > 0:
                    status["analysis"]["exists"] = True
                    status["analysis"]["count"] = analysis_count
                    latest_analysis = db.execute(
                        select(AnalysisResult.pick_date)
                        .order_by(AnalysisResult.pick_date.desc())
                        .limit(1)
                    ).first()
                    if latest_analysis:
                        status["analysis"]["latest_date"] = latest_analysis[0].isoformat()
        except SQLAlchemyError:
            raw_dir = Path(getattr(settings, "data_dir", ROOT)) / "raw"
            candidates_file = Path(getattr(settings, "data_dir", ROOT)) / "candidates" / "candidates_latest.json"
            review_dir = Path(getattr(settings, "data_dir", ROOT)) / "review"
            kline_dir = Path(getattr(settings, "data_dir", ROOT)) / "kline"

            raw_files = list(raw_dir.glob("*.csv")) if raw_dir.exists() else []
            status["raw_data"]["exists"] = bool(raw_files)
            status["raw_data"]["count"] = len(raw_files)
            status["raw_data"]["stock_count"] = len(raw_files)

            if candidates_file.exists():
                status["candidates"]["exists"] = True
                try:
                    payload = json.loads(candidates_file.read_text(encoding="utf-8"))
                    status["candidates"]["count"] = int(payload.get("count", 0) or 0)
                    status["candidates"]["latest_date"] = payload.get("pick_date")
                except Exception:
                    pass

            status["analysis"]["exists"] = review_dir.exists() and any(review_dir.iterdir()) if review_dir.exists() else False
            status["kline"]["exists"] = kline_dir.exists() and any(kline_dir.iterdir()) if kline_dir.exists() else False

        # 更新缓存
        self._data_status_cache[cache_key] = (now, status)
        return status

    @classmethod
    def clear_data_status_cache(cls) -> None:
        """清除数据状态缓存（在数据更新时调用）"""
        cls._data_status_cache.clear()
