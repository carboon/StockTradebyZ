"""
Stock API
~~~~~~~~~
股票数据相关 API
"""
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.api.deps import require_user
from app.database import get_db
from app.models import Stock
from app.services.kline_service import get_daily_data
from app.schemas import (
    StockResponse,
    StockSearchItem,
    StockSearchResponse,
    KLineDataRequest,
    KLineResponse,
    KLineDataPoint,
)
from app.config import settings
from app.services.analysis_service import analysis_service
from app.services.tushare_service import TushareService

router = APIRouter()

ROOT = Path(__file__).parent.parent.parent.parent


def _stock_search_rank(item: dict, keyword: str, normalized_code: str) -> tuple[int, str]:
    code = str(item.get("code", ""))
    name = str(item.get("name", "") or "")
    if normalized_code and code == normalized_code.zfill(6):
        return (0, code)
    if keyword and name == keyword:
        return (1, code)
    if normalized_code and code.startswith(normalized_code):
        return (2, code)
    if keyword and name.startswith(keyword):
        return (3, code)
    return (4, code)


@router.get("/search", response_model=StockSearchResponse)
async def search_stocks(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> StockSearchResponse:
    """按代码或名称搜索股票，支持模糊匹配。"""
    keyword = str(q or "").strip()
    if not keyword:
        return StockSearchResponse(items=[], total=0)

    limit = max(1, min(int(limit or 10), 20))
    normalized_code = "".join(ch for ch in keyword if ch.isdigit())
    items_by_code: dict[str, dict] = {}

    db_filters = []
    if normalized_code:
        db_filters.append(Stock.code.like(f"{normalized_code}%"))
    db_filters.append(Stock.name.like(f"%{keyword}%"))
    db_matches = (
        db.query(Stock)
        .filter(or_(*db_filters))
        .limit(limit * 2)
        .all()
    )
    for stock in db_matches:
        items_by_code[stock.code] = {
            "code": stock.code,
            "name": stock.name,
            "market": stock.market,
            "industry": stock.industry,
        }

    if len(items_by_code) < limit:
        try:
            lookup = TushareService().get_stock_list()
            if lookup is not None and not lookup.empty:
                frame = lookup.copy()
                frame["symbol"] = frame["symbol"].astype(str).str.zfill(6)
                code_mask = frame["symbol"].str.startswith(normalized_code) if normalized_code else False
                name_mask = frame["name"].astype(str).str.contains(keyword, na=False)
                matched = frame[code_mask | name_mask].head(limit * 3)
                for _, row in matched.iterrows():
                    code = str(row.get("symbol", "")).zfill(6)
                    if not code or code == "000000":
                        continue
                    items_by_code.setdefault(code, {
                        "code": code,
                        "name": row.get("name"),
                        "market": TushareService._to_exchange(row.get("ts_code", "")),
                        "industry": row.get("industry"),
                    })
        except Exception:
            pass

    ranked_items = sorted(
        items_by_code.values(),
        key=lambda item: _stock_search_rank(item, keyword, normalized_code),
    )[:limit]
    return StockSearchResponse(
        items=[StockSearchItem(**item) for item in ranked_items],
        total=len(ranked_items),
    )


@router.get("/{code}", response_model=StockResponse)
async def get_stock_info(code: str, db: Session = Depends(get_db), user=Depends(require_user)) -> StockResponse:
    """获取股票基本信息（只读模式，不触发自动同步）"""
    code = code.zfill(6)
    stock = db.query(Stock).filter(Stock.code == code).first()

    # 检查数据是否存在
    csv_path = ROOT / settings.raw_data_dir / f"{code}.csv"
    exists = csv_path.exists()

    if stock:
        return StockResponse(
            code=stock.code,
            name=stock.name,
            market=stock.market,
            industry=stock.industry,
            exists=True,
        )

    # GET 接口不触发自动同步（只读模式）
    # 如果数据库中不存在，返回基本信息，不调用 sync_stock_to_db
    # 数据同步应由后台任务负责
    return StockResponse(code=code, exists=exists)


@router.post("/kline", response_model=KLineResponse)
async def get_kline_data(request: KLineDataRequest, db: Session = Depends(get_db), user=Depends(require_user)) -> KLineResponse:
    """获取 K线数据（纯数据库版本）"""
    code = request.code.zfill(6)

    try:
        # 从数据库获取数据
        end = date.today()
        start = end - timedelta(days=request.days * 2)  # 多取一些确保足够
        db_df = get_daily_data(db, code, start, end)

        if db_df is None or db_df.empty:
            raise HTTPException(status_code=404, detail=f"股票 {code} 数据不存在，请先执行数据初始化")

        # 统一列名：数据库返回 volume
        df = db_df.rename(columns={"volume": "vol"}) if "volume" in db_df.columns else db_df.copy()
        df["date"] = pd.to_datetime(df["date"])

        # 验证必需的列存在
        required_cols = ["date", "open", "high", "low", "close"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise HTTPException(
                status_code=500,
                detail=f"数据缺少必需的列: {', '.join(missing_cols)}"
            )

        # 取最近 N 天
        if request.days > 0:
            df = df.tail(request.days).copy()

        # 计算均线
        df["ma5"] = df["close"].rolling(window=5).mean()
        df["ma10"] = df["close"].rolling(window=10).mean()
        df["ma20"] = df["close"].rolling(window=20).mean()
        df["ma60"] = df["close"].rolling(window=60).mean()

        # 确定成交量列名（可能是 vol 或 volume）
        vol_col = "vol" if "vol" in df.columns else "volume" if "volume" in df.columns else None

        # 转换为响应格式
        daily_data = []
        for _, row in df.iterrows():
            try:
                volume_val = 0
                if vol_col:
                    volume_val = float(row.get(vol_col, 0)) if not pd.isna(row.get(vol_col)) else 0

                daily_data.append(
                    KLineDataPoint(
                        date=row["date"].strftime("%Y-%m-%d"),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=volume_val,
                        ma5=float(row["ma5"]) if not pd.isna(row["ma5"]) else None,
                        ma10=float(row["ma10"]) if not pd.isna(row["ma10"]) else None,
                        ma20=float(row["ma20"]) if not pd.isna(row["ma20"]) else None,
                        ma60=float(row["ma60"]) if not pd.isna(row["ma60"]) else None,
                    )
                )
            except (ValueError, TypeError):
                # 跳过有问题的行
                continue

        weekly_data = None
        if request.include_weekly and len(df) > 5 and vol_col:
            try:
                # 转换为周线
                df_copy = df.copy()
                df_copy["year_week"] = df_copy["date"].dt.isocalendar().week.astype(str)
                df_copy["year"] = df_copy["date"].dt.year.astype(str)
                df_copy["week_key"] = df_copy["year"] + "-" + df_copy["year_week"]

                weekly = (
                    df_copy.groupby("week_key")
                    .agg({
                        "date": "first",
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        vol_col: "sum",
                    })
                    .reset_index(drop=True)
                )

                weekly["ma5"] = weekly["close"].rolling(window=5).mean()
                weekly["ma10"] = weekly["close"].rolling(window=10).mean()

                weekly_data = []
                for _, row in weekly.iterrows():
                    try:
                        weekly_data.append(
                            KLineDataPoint(
                                date=row["date"].strftime("%Y-%m-%d"),
                                open=float(row["open"]),
                                high=float(row["high"]),
                                low=float(row["low"]),
                                close=float(row["close"]),
                                volume=float(row[vol_col]) if not pd.isna(row[vol_col]) else 0,
                                ma5=float(row["ma5"]) if not pd.isna(row["ma5"]) else None,
                                ma10=float(row["ma10"]) if not pd.isna(row["ma10"]) else None,
                            )
                        )
                    except (ValueError, TypeError):
                        # 跳过有问题的行
                        continue
            except Exception:
                # 如果周线计算失败，忽略周线数据
                weekly_data = None

        return KLineResponse(
            code=code,
            name=None,
            daily=daily_data,
            weekly=weekly_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"加载K线数据失败: {str(e)}")
