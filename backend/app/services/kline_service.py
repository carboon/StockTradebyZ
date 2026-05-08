"""
K-Line Data Service
~~~~~~~~~~~~~~~~~~~
K 线数据的数据库读写服务 - 纯数据库版本
不再依赖 CSV 文件
"""
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import distinct
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Stock, StockDaily
from app.utils.stock_metadata import normalize_stock_code, resolve_market

logger = logging.getLogger(__name__)

_OPTIONAL_DAILY_METRIC_COLUMNS = [
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "free_share",
    "circ_mv",
    "buy_sm_amount",
    "sell_sm_amount",
    "buy_md_amount",
    "sell_md_amount",
    "buy_lg_amount",
    "sell_lg_amount",
    "buy_elg_amount",
    "sell_elg_amount",
    "net_mf_amount",
]


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def ensure_stock_row(db: Session, code: str) -> Stock:
    """确保 stocks 表存在对应 code，避免 stock_daily 外键写入失败。"""
    normalized_code = normalize_stock_code(code)
    if not normalized_code:
        raise ValueError(f"无效股票代码: {code!r}")

    stock = db.query(Stock).filter(Stock.code == normalized_code).first()
    if stock is not None:
        return stock

    stock = Stock(
        code=normalized_code,
        market=resolve_market(normalized_code),
    )
    db.add(stock)
    # 显式 flush，让后续对 stock_daily 的查询/插入在同一事务中能安全引用父记录。
    db.flush()
    return stock


def save_daily_data(db: Session, code: str, df: pd.DataFrame) -> int:
    """将单只股票的日线数据 upsert 到数据库

    Args:
        db: 数据库 session
        code: 股票代码
        df: DataFrame，必须包含 date, open, close, high, low, volume 列

    Returns:
        插入/更新的行数
    """
    if df.empty:
        return 0

    normalized_code = normalize_stock_code(code)
    if not normalized_code:
        raise ValueError(f"无效股票代码: {code!r}")

    ensure_stock_row(db, normalized_code)

    records: list[dict] = []
    for _, row in df.iterrows():
        trade_date = row.get("date")
        if isinstance(trade_date, str):
            trade_date = pd.to_datetime(trade_date).date()
        elif isinstance(trade_date, (datetime, pd.Timestamp)):
            trade_date = trade_date.date() if hasattr(trade_date, 'date') else trade_date

        record = {
            "code": normalized_code,
            "trade_date": trade_date,
            "open": float(row["open"]),
            "close": float(row["close"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "volume": float(row["volume"]),
        }
        for column in _OPTIONAL_DAILY_METRIC_COLUMNS:
            if column in df.columns:
                record[column] = _optional_float(row.get(column))
        records.append(record)

    if not records:
        return 0

    stmt = pg_insert(StockDaily.__table__).values(records)
    stmt = stmt.on_conflict_do_update(
        index_elements=["code", "trade_date"],
        set_={
            "open": stmt.excluded.open,
            "close": stmt.excluded.close,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "volume": stmt.excluded.volume,
            "turnover_rate": stmt.excluded.turnover_rate,
            "turnover_rate_f": stmt.excluded.turnover_rate_f,
            "volume_ratio": stmt.excluded.volume_ratio,
            "free_share": stmt.excluded.free_share,
            "circ_mv": stmt.excluded.circ_mv,
            "buy_sm_amount": stmt.excluded.buy_sm_amount,
            "sell_sm_amount": stmt.excluded.sell_sm_amount,
            "buy_md_amount": stmt.excluded.buy_md_amount,
            "sell_md_amount": stmt.excluded.sell_md_amount,
            "buy_lg_amount": stmt.excluded.buy_lg_amount,
            "sell_lg_amount": stmt.excluded.sell_lg_amount,
            "buy_elg_amount": stmt.excluded.buy_elg_amount,
            "sell_elg_amount": stmt.excluded.sell_elg_amount,
            "net_mf_amount": stmt.excluded.net_mf_amount,
        },
    )

    db.execute(stmt)

    db.commit()
    return len(records)


def bulk_save_daily_data(db: Session, data: dict[str, pd.DataFrame]) -> int:
    """批量写入多只股票的日线数据

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
    """从数据库读取 K 线数据

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
            "turnover_rate": row.turnover_rate,
            "turnover_rate_f": row.turnover_rate_f,
            "volume_ratio": row.volume_ratio,
            "free_share": row.free_share,
            "circ_mv": row.circ_mv,
            "buy_sm_amount": row.buy_sm_amount,
            "sell_sm_amount": row.sell_sm_amount,
            "buy_md_amount": row.buy_md_amount,
            "sell_md_amount": row.sell_md_amount,
            "buy_lg_amount": row.buy_lg_amount,
            "sell_lg_amount": row.sell_lg_amount,
            "buy_elg_amount": row.buy_elg_amount,
            "sell_elg_amount": row.sell_elg_amount,
            "net_mf_amount": row.net_mf_amount,
        })

    return pd.DataFrame(data)


def get_all_codes_with_data(db: Session) -> list[str]:
    """获取数据库中有 K 线数据的所有股票代码"""
    results = db.query(distinct(StockDaily.code)).all()
    return [r[0] for r in results]


def get_latest_trade_date(db: Session, code: str) -> Optional[date]:
    """获取指定股票在数据库中最新的交易日期"""
    result = (
        db.query(StockDaily.trade_date)
        .filter(StockDaily.code == code)
        .order_by(StockDaily.trade_date.desc())
        .first()
    )
    return result[0] if result else None


def get_all_daily_data(db: Session) -> dict[str, pd.DataFrame]:
    """获取数据库中所有股票的 K 线数据

    Returns:
        {code: DataFrame} 字典
    """
    codes = get_all_codes_with_data(db)
    data = {}

    logger.info("从数据库加载 %d 只股票的 K 线数据", len(codes))

    for code in codes:
        df = get_daily_data(db, code)
        if not df.empty:
            data[code] = df

    return data


def check_data_completeness(db: Session, code: str, expected_days: int = 250) -> dict:
    """检查股票数据完整性

    Args:
        db: 数据库 session
        code: 股票代码
        expected_days: 期望的交易日数量（默认250，约一年）

    Returns:
        {has_data, days_count, latest_date, is_complete} 字典
    """
    latest = get_latest_trade_date(db, code)

    if not latest:
        return {
            "has_data": False,
            "days_count": 0,
            "latest_date": None,
            "is_complete": False
        }

    count = db.query(StockDaily).filter(
        StockDaily.code == code
    ).count()

    # 计算最新日期到今天的交易日差距
    today = date.today()
    days_diff = (today - latest).days

    return {
        "has_data": True,
        "days_count": count,
        "latest_date": latest,
        "is_complete": count >= expected_days and days_diff <= 7  # 允许一周延迟
    }


__all__ = [
    "ensure_stock_row",
    "save_daily_data",
    "bulk_save_daily_data",
    "get_daily_data",
    "get_all_codes_with_data",
    "get_latest_trade_date",
    "get_all_daily_data",
    "check_data_completeness",
]
