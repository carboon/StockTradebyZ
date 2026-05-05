"""
Daily Data Service (Database-Only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
K线数据服务 - 完全基于数据库，支持增量更新

数据流：
Tushare API → 数据库 → 应用层
不再依赖 CSV 文件
"""
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List

import pandas as pd
import requests
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Stock, StockDaily
from app.services.kline_service import ensure_stock_row
from app.utils.stock_metadata import normalize_stock_code, resolve_ts_code
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).parent.parent.parent.parent
logger = logging.getLogger(__name__)


class DailyDataService:
    """K线数据服务 - 数据库版本"""

    def __init__(self, token: Optional[str] = None):
        if token is None:
            token = settings.tushare_token
        self.token = token
        self._pro = None

    @property
    def pro(self):
        """延迟初始化 Tushare pro"""
        if self._pro is None:
            import tushare as ts
            self._pro = ts.pro_api(self.token)
        return self._pro

    def get_latest_trade_date(self) -> Optional[str]:
        """获取数据库中最新交易日期"""
        with SessionLocal() as db:
            result = db.execute(
                select(StockDaily.trade_date)
                .order_by(StockDaily.trade_date.desc())
                .limit(1)
            ).first()
            return result[0].strftime("%Y-%m-%d") if result else None

    def get_stock_list(self) -> List[str]:
        """获取需要更新的股票代码列表"""
        with SessionLocal() as db:
            stocks = db.execute(
                select(Stock.code)
                .order_by(Stock.code)
            ).scalars().all()
            return list(stocks)

    def get_stock_latest_date(self, code: str) -> Optional[date]:
        """获取指定股票的最新数据日期"""
        with SessionLocal() as db:
            result = db.execute(
                select(StockDaily.trade_date)
                .where(StockDaily.code == code)
                .order_by(StockDaily.trade_date.desc())
                .limit(1)
            ).first()
            return result[0] if result else None

    def fetch_daily_data(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """从 Tushare 获取日线数据

        Args:
            code: 股票代码 (6位)
            start_date: 开始日期 (YYYYMMDD)
            end_date: 结束日期 (YYYYMMDD)

        Returns:
            DataFrame with columns: trade_date, open, high, low, close, vol
        """
        try:
            ts_code = resolve_ts_code(code)
            acquire_tushare_slot("daily")

            if start_date:
                start_date = start_date.replace("-", "")
            if end_date:
                end_date = end_date.replace("-", "")

            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df is None or df.empty:
                return None

            # 重命名列并格式化
            df = df.rename(columns={
                "trade_date": "trade_date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "vol": "volume"
            })

            # 只保留需要的列
            df = df[["trade_date", "open", "high", "low", "close", "volume"]]
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df["code"] = code

            return df.sort_values("trade_date").reset_index(drop=True)

        except Exception as e:
            logger.error(f"获取 {code} 数据失败: {e}")
            return None

    def save_daily_data(self, df: pd.DataFrame) -> int:
        """保存日线数据到数据库

        Args:
            df: DataFrame with columns: code, trade_date, open, high, low, close, volume

        Returns:
            保存的记录数
        """
        if df is None or df.empty:
            return 0

        with SessionLocal() as db:
            saved_count = 0
            ensured_codes: set[str] = set()
            for _, row in df.iterrows():
                normalized_code = normalize_stock_code(row["code"])
                if not normalized_code:
                    raise ValueError(f"无效股票代码: {row['code']!r}")

                if normalized_code not in ensured_codes:
                    ensure_stock_row(db, normalized_code)
                    ensured_codes.add(normalized_code)

                # 检查是否已存在
                existing = db.execute(
                    select(StockDaily)
                    .where(
                        StockDaily.code == normalized_code,
                        StockDaily.trade_date == row["trade_date"]
                    )
                ).scalar_one_or_none()

                if existing:
                    # 更新
                    existing.open = float(row["open"])
                    existing.high = float(row["high"])
                    existing.low = float(row["low"])
                    existing.close = float(row["close"])
                    existing.volume = float(row["volume"])
                else:
                    # 插入
                    record = StockDaily(
                        code=normalized_code,
                        trade_date=row["trade_date"],
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"])
                    )
                    db.add(record)
                    saved_count += 1

            try:
                db.commit()
                return saved_count
            except Exception as e:
                db.rollback()
                logger.error(f"保存数据失败: {e}")
                return 0

    def get_daily_data(
        self,
        code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> Optional[pd.DataFrame]:
        """从数据库获取日线数据

        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame with columns: date, open, high, low, close, vol
        """
        with SessionLocal() as db:
            query = select(StockDaily).where(StockDaily.code == code)

            if start_date:
                query = query.where(StockDaily.trade_date >= start_date)
            if end_date:
                query = query.where(StockDaily.trade_date <= end_date)

            query = query.order_by(StockDaily.trade_date)

            results = db.execute(query).scalars().all()
            if not results:
                return None

            data = [{
                "date": r.trade_date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "vol": float(r.volume)
            } for r in results]

            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").reset_index(drop=True)

    def incremental_update(
        self,
        end_date: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> dict:
        """增量更新所有股票的日线数据

        Args:
            end_date: 结束日期 (YYYY-MM-DD)
            progress_callback: 进度回调函数 callback(current, total, code, status)

        Returns:
            更新结果: {success, total, updated, skipped, failed, message}
        """
        # 规范化日期
        if end_date:
            end_date = end_date.replace("-", "")
        else:
            end_date = datetime.now().strftime("%Y%m%d")

        # 获取需要更新的股票列表
        codes = self.get_stock_list()
        if not codes:
            return {
                "success": False,
                "message": "没有找到股票列表，请先执行全量初始化"
            }

        total = len(codes)
        updated = 0
        skipped = 0
        failed = 0
        failed_codes = []

        def emit_progress(current: int, code: Optional[str], status: str, message: str) -> None:
            if not progress_callback:
                return
            progress = int(current / total * 100) if total > 0 else 0
            progress_callback({
                "current": current,
                "total": total,
                "progress": progress,
                "current_code": code,
                "updated_count": updated,
                "skipped_count": skipped,
                "failed_count": failed,
                "message": message,
                "status": status,
            })

        emit_progress(0, None, "starting", "准备更新...")

        for i, code in enumerate(codes):
            current = i + 1

            # 获取该股票最新日期
            latest_date = self.get_stock_latest_date(code)

            if latest_date:
                # 已有数据，增量更新
                start_date = (latest_date + timedelta(days=1)).strftime("%Y%m%d")
            else:
                # 没有数据，获取最近一年
                start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

            # 获取数据
            df = self.fetch_daily_data(code, start_date, end_date)

            if df is None or df.empty:
                failed += 1
                failed_codes.append(code)
                emit_progress(current, code, "failed", f"{code} 无可更新数据或拉取失败")
                continue

            # 保存数据
            count = self.save_daily_data(df)
            if count > 0:
                updated += 1
                emit_progress(current, code, "updated", f"{code} 更新 {count} 条记录")
            else:
                skipped += 1
                emit_progress(current, code, "skipped", f"{code} 无新增记录")

        emit_progress(total, None, "completed", f"更新完成: {updated} 更新, {skipped} 跳过, {failed} 失败")

        return {
            "success": True,
            "total": total,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
            "failed_codes": failed_codes,
            "message": f"更新完成: {updated} 更新, {skipped} 跳过, {failed} 失败"
        }

    def get_data_status(self) -> dict:
        """获取数据状态统计"""
        with SessionLocal() as db:
            # 统计股票数量
            stock_count = db.execute(
                select(Stock.code).count()
            ).scalar() or 0

            # 统计K线数据量
            kline_count = db.execute(
                select(StockDaily.id).count()
            ).scalar() or 0

            # 获取最新日期
            latest_result = db.execute(
                select(StockDaily.trade_date)
                .order_by(StockDaily.trade_date.desc())
                .limit(1)
            ).first()

            latest_date = latest_result[0] if latest_result else None

            # 统计有数据的股票数
            stocks_with_data = db.execute(
                select(StockDaily.code).distinct().count()
            ).scalar() or 0

            return {
                "raw_data": {
                    "exists": stock_count > 0,
                    "count": stock_count,
                    "latest_date": latest_date.isoformat() if latest_date else None,
                    "stocks_with_data": stocks_with_data,
                    "kline_records": kline_count
                }
            }

    def ensure_stock_exists(self, code: str, name: str = None, market: str = None):
        """确保股票信息存在"""
        with SessionLocal() as db:
            existing = db.get(Stock, code)
            if not existing:
                stock = Stock(code=code, name=name, market=market)
                db.add(stock)
                db.commit()

    def batch_import_from_csv(self, csv_dir: Path, progress_callback: Optional[callable] = None) -> dict:
        """从 CSV 目录批量导入历史数据

        Args:
            csv_dir: CSV 文件目录
            progress_callback: 进度回调

        Returns:
            导入结果统计
        """
        if not csv_dir.exists():
            return {"success": False, "message": "CSV 目录不存在"}

        csv_files = list(csv_dir.glob("*.csv"))
        if not csv_files:
            return {"success": False, "message": "没有找到 CSV 文件"}

        total = len(csv_files)
        imported = 0
        failed = 0

        for i, csv_path in enumerate(csv_files, 1):
            code = csv_path.stem  # 文件名即股票代码

            try:
                df = pd.read_csv(csv_path)
                df.columns = [c.lower() for c in df.columns]

                # 标准化列名
                column_map = {
                    "trade_date": "trade_date",
                    "date": "trade_date",
                    "vol": "volume"
                }
                df = df.rename(columns=column_map)

                # 确保 code 列存在
                if "code" not in df.columns:
                    df["code"] = code

                # 确保 trade_date 是 date 类型
                if "trade_date" in df.columns:
                    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

                # 保存到数据库
                count = self.save_daily_data(df)
                if count > 0:
                    imported += 1

                if progress_callback:
                    progress_callback(i, total, code, "imported")

            except Exception as e:
                logger.error(f"导入 {code} 失败: {e}")
                failed += 1
                if progress_callback:
                    progress_callback(i, total, code, "failed")

        return {
            "success": True,
            "total": total,
            "imported": imported,
            "failed": failed,
            "message": f"导入完成: {imported} 成功, {failed} 失败"
        }


# 全局实例
_daily_data_service: Optional[DailyDataService] = None


def get_daily_data_service() -> DailyDataService:
    """获取 DailyData 服务单例"""
    global _daily_data_service
    if _daily_data_service is None:
        _daily_data_service = DailyDataService()
    return _daily_data_service
