"""
K-Line Data Service
~~~~~~~~~~~~~~~~~~~
K 线数据的数据库读写服务层，支持 CSV 回退。
"""
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import StockDaily

logger = logging.getLogger(__name__)


def save_daily_data(db: Session, code: str, df: pd.DataFrame) -> int:
    """将单只股票的日线数据 upsert 到数据库。

    Args:
        db: 数据库 session
        code: 股票代码
        df: DataFrame，必须包含 date, open, close, high, low, volume 列

    Returns:
        插入/更新的行数
    """
    if df.empty:
        return 0

    count = 0
    for _, row in df.iterrows():
        trade_date = row.get("date")
        if isinstance(trade_date, str):
            trade_date = pd.to_datetime(trade_date).date()
        elif isinstance(trade_date, (datetime, pd.Timestamp)):
            trade_date = trade_date.date() if hasattr(trade_date, 'date') else trade_date

        existing = db.query(StockDaily).filter(
            StockDaily.code == code,
            StockDaily.trade_date == trade_date,
        ).first()

        if existing:
            existing.open = float(row["open"])
            existing.close = float(row["close"])
            existing.high = float(row["high"])
            existing.low = float(row["low"])
            existing.volume = float(row["volume"])
        else:
            db.add(StockDaily(
                code=code,
                trade_date=trade_date,
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                volume=float(row["volume"]),
            ))
        count += 1

    db.commit()
    return count


def bulk_save_daily_data(db: Session, data: dict[str, pd.DataFrame]) -> int:
    """批量写入多只股票的日线数据。

    Args:
        data: {code: DataFrame} 字典

    Returns:
        总写入行数
    """
    total = 0
    for code, df in data.items():
        total += save_daily_data(db, code, df)
    return total


def get_daily_data(
    db: Session,
    code: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """从数据库读取 K 线数据。

    Args:
        db: 数据库 session
        code: 股票代码
        start_date: 起始日期（可选）
        end_date: 结束日期（可选）

    Returns:
        DataFrame with columns: date, open, close, high, low, volume
    """
    query = db.query(StockDaily).filter(StockDaily.code == code)

    if start_date:
        query = query.filter(StockDaily.trade_date >= start_date)
    if end_date:
        query = query.filter(StockDaily.trade_date <= end_date)

    rows = query.order_by(StockDaily.trade_date).all()

    if not rows:
        return pd.DataFrame()

    data = []
    for row in rows:
        data.append({
            "date": row.trade_date,
            "open": row.open,
            "close": row.close,
            "high": row.high,
            "low": row.low,
            "volume": row.volume,
        })

    return pd.DataFrame(data)


def get_all_codes_with_data(db: Session) -> list[str]:
    """获取数据库中有 K 线数据的所有股票代码。"""
    from sqlalchemy import distinct
    results = db.query(distinct(StockDaily.code)).all()
    return [r[0] for r in results]


def get_latest_trade_date(db: Session, code: str) -> Optional[date]:
    """获取指定股票在数据库中最新的交易日期。"""
    result = (
        db.query(StockDaily.trade_date)
        .filter(StockDaily.code == code)
        .order_by(StockDaily.trade_date.desc())
        .first()
    )
    return result[0] if result else None


def load_daily_data_from_csv(raw_dir: Optional[Path] = None) -> dict[str, pd.DataFrame]:
    """从 CSV 文件加载 K 线数据（回退方法）。

    Args:
        raw_dir: CSV 文件目录，默认使用配置中的 raw_data_dir

    Returns:
        {code: DataFrame} 字典
    """
    data_dir = raw_dir or settings.raw_data_dir
    data: dict[str, pd.DataFrame] = {}

    if not data_dir.exists():
        return data

    csv_files = list(data_dir.glob("*.csv"))
    logger.info("从 CSV 加载 K 线数据: %d 个文件", len(csv_files))

    for csv_path in csv_files:
        code = csv_path.stem
        try:
            df = pd.read_csv(csv_path)
            if not df.empty and "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                data[code] = df
        except Exception as e:
            logger.warning("读取 CSV 失败 %s: %s", csv_path.name, e)

    return data


def load_daily_data(
    db: Session,
    use_db: bool = True,
    raw_dir: Optional[Path] = None,
) -> dict[str, pd.DataFrame]:
    """智能加载 K 线数据：优先 DB，回退 CSV。

    Args:
        db: 数据库 session
        use_db: 是否尝试从数据库加载
        raw_dir: CSV 回退目录

    Returns:
        {code: DataFrame} 字典
    """
    if use_db:
        codes = get_all_codes_with_data(db)
        if codes:
            logger.info("从数据库加载 %d 只股票的 K 线数据", len(codes))
            data = {}
            for code in codes:
                df = get_daily_data(db, code)
                if not df.empty:
                    data[code] = df
            if data:
                return data
            logger.info("数据库无有效数据，回退到 CSV")

    return load_daily_data_from_csv(raw_dir)
