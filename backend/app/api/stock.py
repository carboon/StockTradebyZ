"""
Stock API
~~~~~~~~~
股票数据相关 API
"""
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Stock
from app.schemas import StockResponse, KLineDataRequest, KLineResponse, KLineDataPoint
from app.config import settings
from app.services.analysis_service import analysis_service
from app.services.tushare_service import TushareService

router = APIRouter()

ROOT = Path(__file__).parent.parent.parent.parent


@router.get("/{code}", response_model=StockResponse)
async def get_stock_info(code: str, db: Session = Depends(get_db)) -> StockResponse:
    """获取股票基本信息"""
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

    try:
        synced_stock = TushareService().sync_stock_to_db(db, code)
        if synced_stock:
            return StockResponse(
                code=synced_stock.code,
                name=synced_stock.name,
                market=synced_stock.market,
                industry=synced_stock.industry,
                exists=exists,
            )
    except Exception:
        pass

    return StockResponse(code=code, exists=exists)


@router.post("/kline", response_model=KLineResponse)
async def get_kline_data(request: KLineDataRequest) -> KLineResponse:
    """获取 K线数据"""
    code = request.code.zfill(6)

    try:
        # 使用 analysis_service 加载数据
        df = analysis_service.load_stock_data(code)

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail=f"股票 {code} 数据不存在")

        # 验证必需的列存在
        required_cols = ["date", "open", "high", "low", "close"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise HTTPException(
                status_code=500,
                detail=f"数据文件缺少必需的列: {', '.join(missing_cols)}"
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
            except (ValueError, TypeError) as e:
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
                    .agg(
                        {
                            "date": "first",
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            vol_col: "sum",
                        }
                    )
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
