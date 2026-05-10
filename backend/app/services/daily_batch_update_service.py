"""
Daily Batch Update Service
~~~~~~~~~~~~~~~~~~~~~~~~~~
按交易日批量抓取全市场日线，先落地日分片文件，再批量入库并更新 manifest。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Callable

import pandas as pd
from sqlalchemy import select, func, distinct
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import StockDaily
from app.services.daily_data_service import bulk_upsert_stock_daily
from app.services.raw_data_manifest_service import RawDataManifestService
from app.services.tushare_service import TushareService
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).parent.parent.parent.parent
logger = logging.getLogger(__name__)


class DailyBatchUpdateService:
    """按交易日批量抓取并入库。"""

    def __init__(self, db: Optional[Session] = None, token: Optional[str] = None):
        self.db = db or SessionLocal()
        self._owns_session = db is None
        self.tushare_service = TushareService(token=token)
        self.manifest_service = RawDataManifestService(self.db)

    def __enter__(self) -> "DailyBatchUpdateService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._owns_session:
            self.db.close()

    def _daily_partition_path(self, trade_date: str) -> Path:
        return ROOT / "data" / "raw_daily" / f"{trade_date}.jsonl"

    def fetch_trade_date_snapshot(self, trade_date: str) -> pd.DataFrame:
        normalized = trade_date.replace("-", "")
        acquire_tushare_slot("daily")
        frame = self.tushare_service.pro.daily(trade_date=normalized)
        if frame is None or frame.empty:
            return pd.DataFrame()

        frame = frame.rename(
            columns={
                "ts_code": "ts_code",
                "trade_date": "trade_date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "vol": "volume",
            }
        )
        frame = frame[["ts_code", "trade_date", "open", "high", "low", "close", "volume"]].copy()
        acquire_tushare_slot("daily_basic")
        daily_basic = self.tushare_service.pro.daily_basic(
            trade_date=normalized,
            fields="ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,free_share,circ_mv",
        )
        if daily_basic is None:
            daily_basic = pd.DataFrame()
        acquire_tushare_slot("moneyflow")
        moneyflow = self.tushare_service.pro.moneyflow(
            trade_date=normalized,
            fields=(
                "ts_code,trade_date,buy_sm_amount,sell_sm_amount,"
                "buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,"
                "buy_elg_amount,sell_elg_amount,net_mf_amount"
            ),
        )
        if moneyflow is None:
            moneyflow = pd.DataFrame()
        frame = frame.merge(daily_basic, on=["ts_code", "trade_date"], how="left")
        frame = frame.merge(moneyflow, on=["ts_code", "trade_date"], how="left")
        frame["code"] = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        return frame.sort_values(["trade_date", "code"]).reset_index(drop=True)

    def _frame_to_records(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            records.append(
                {
                    "code": str(row["code"]).zfill(6),
                    "trade_date": row["trade_date"],
                    "open": float(row["open"]),
                    "close": float(row["close"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "volume": float(row["volume"]),
                    "turnover_rate": float(row["turnover_rate"]) if pd.notna(row.get("turnover_rate")) else None,
                    "turnover_rate_f": float(row["turnover_rate_f"]) if pd.notna(row.get("turnover_rate_f")) else None,
                    "volume_ratio": float(row["volume_ratio"]) if pd.notna(row.get("volume_ratio")) else None,
                    "free_share": float(row["free_share"]) if pd.notna(row.get("free_share")) else None,
                    "circ_mv": float(row["circ_mv"]) if pd.notna(row.get("circ_mv")) else None,
                    "buy_sm_amount": float(row["buy_sm_amount"]) if pd.notna(row.get("buy_sm_amount")) else None,
                    "sell_sm_amount": float(row["sell_sm_amount"]) if pd.notna(row.get("sell_sm_amount")) else None,
                    "buy_md_amount": float(row["buy_md_amount"]) if pd.notna(row.get("buy_md_amount")) else None,
                    "sell_md_amount": float(row["sell_md_amount"]) if pd.notna(row.get("sell_md_amount")) else None,
                    "buy_lg_amount": float(row["buy_lg_amount"]) if pd.notna(row.get("buy_lg_amount")) else None,
                    "sell_lg_amount": float(row["sell_lg_amount"]) if pd.notna(row.get("sell_lg_amount")) else None,
                    "buy_elg_amount": float(row["buy_elg_amount"]) if pd.notna(row.get("buy_elg_amount")) else None,
                    "sell_elg_amount": float(row["sell_elg_amount"]) if pd.notna(row.get("sell_elg_amount")) else None,
                    "net_mf_amount": float(row["net_mf_amount"]) if pd.notna(row.get("net_mf_amount")) else None,
                    "ts_code": row["ts_code"],
                }
            )
        return records

    def _save_snapshot_file(self, trade_date: str, records: list[dict[str, Any]]) -> tuple[Path, int, str]:
        path = self._daily_partition_path(trade_date)
        record_count, file_size = self.manifest_service.serialize_json_lines(records, path)
        checksum = self.manifest_service.calculate_file_checksum(path)
        return path, file_size, checksum

    @staticmethod
    def _sync_raw_csv_files(frame: pd.DataFrame) -> None:
        raw_dir = ROOT / settings.raw_data_dir
        raw_dir.mkdir(parents=True, exist_ok=True)

        normalized = frame.copy()
        normalized["trade_date"] = pd.to_datetime(normalized["trade_date"])

        for code, group in normalized.groupby("code", sort=False):
            csv_path = raw_dir / f"{str(code).zfill(6)}.csv"
            csv_df = group.rename(columns={"trade_date": "date"}).drop(columns=["ts_code"], errors="ignore").copy()

            if csv_path.exists():
                try:
                    existing = pd.read_csv(csv_path)
                    if not existing.empty:
                        existing["date"] = pd.to_datetime(existing["date"])
                        csv_df = pd.concat([existing, csv_df], ignore_index=True)
                except Exception as exc:
                    logger.warning("读取已有 raw CSV 失败，继续覆盖重建 %s: %s", csv_path, exc)

            csv_df = csv_df.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)
            csv_df.to_csv(csv_path, index=False)

    def _load_records_to_db(self, records: list[dict[str, Any]]) -> tuple[int, int]:
        kline_records = [
            {
                "code": item["code"],
                "trade_date": item["trade_date"],
                "open": item["open"],
                "close": item["close"],
                "high": item["high"],
                "low": item["low"],
                "volume": item["volume"],
                "turnover_rate": item.get("turnover_rate"),
                "turnover_rate_f": item.get("turnover_rate_f"),
                "volume_ratio": item.get("volume_ratio"),
                "free_share": item.get("free_share"),
                "circ_mv": item.get("circ_mv"),
                "buy_sm_amount": item.get("buy_sm_amount"),
                "sell_sm_amount": item.get("sell_sm_amount"),
                "buy_md_amount": item.get("buy_md_amount"),
                "sell_md_amount": item.get("sell_md_amount"),
                "buy_lg_amount": item.get("buy_lg_amount"),
                "sell_lg_amount": item.get("sell_lg_amount"),
                "buy_elg_amount": item.get("buy_elg_amount"),
                "sell_elg_amount": item.get("sell_elg_amount"),
                "net_mf_amount": item.get("net_mf_amount"),
            }
            for item in records
        ]
        result = bulk_upsert_stock_daily(self.db, kline_records)

        if not records:
            return result["inserted"], 0

        trade_date = records[0]["trade_date"]
        db_stock_count = self.db.execute(
            select(func.count(distinct(StockDaily.code))).where(StockDaily.trade_date == trade_date)
        ).scalar() or 0
        return int(result["inserted"] or 0), int(db_stock_count or 0)

    @staticmethod
    def _emit_progress(
        progress_callback: Optional[Callable[[dict[str, Any]], None]],
        *,
        stage: str,
        progress: int,
        trade_date: str,
        message: str,
        **extra: Any,
    ) -> None:
        if not progress_callback:
            return
        payload = {
            "stage": stage,
            "percent": progress,
            "progress": progress,
            "current": extra.pop("current", None),
            "total": extra.pop("total", None),
            "current_code": trade_date,
            "message": message,
        }
        payload.update(extra)
        progress_callback(payload)

    def update_trade_date(
        self,
        trade_date: str,
        source: str = "daily_batch",
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
        sync_raw_csv: bool = True,
    ) -> dict[str, Any]:
        trade_day = datetime.fromisoformat(trade_date).date()
        self._emit_progress(
            progress_callback,
            stage="daily_batch_prepare",
            progress=5,
            trade_date=trade_date,
            message=f"准备按交易日批量刷新 {trade_date}",
            total=1,
            current=0,
        )
        batch = self.manifest_service.create_batch(
            batch_type="daily_trade_date",
            trade_date=trade_day,
            source=source,
            meta={"mode": "daily_batch"},
        )

        try:
            self._emit_progress(
                progress_callback,
                stage="daily_batch_fetch",
                progress=20,
                trade_date=trade_date,
                message=f"抓取 {trade_date} 全市场日线快照",
                total=1,
                current=0,
            )
            frame = self.fetch_trade_date_snapshot(trade_date)
            if frame.empty:
                self.manifest_service.complete_batch(
                    batch,
                    status="failed",
                    error_message=f"{trade_date} 未获取到日线快照",
                    meta={"mode": "daily_batch", "reason": "empty_snapshot"},
                )
                self.manifest_service.upsert_manifest(
                    trade_date=trade_day,
                    status="failed",
                    source=source,
                    batch_id=batch.id,
                    meta={"reason": "empty_snapshot"},
                )
                return {"ok": False, "message": f"{trade_date} 未获取到日线快照"}

            self._emit_progress(
                progress_callback,
                stage="daily_batch_persist_raw",
                progress=55,
                trade_date=trade_date,
                message=f"写入 {trade_date} 原始日分片文件",
                total=1,
                current=0,
                record_count=int(len(frame.index)),
                stock_count=int(frame["code"].nunique()),
            )
            records = self._frame_to_records(frame)
            snapshot_path, file_size, checksum = self._save_snapshot_file(trade_date, records)
            if sync_raw_csv:
                self._sync_raw_csv_files(frame)

            self._emit_progress(
                progress_callback,
                stage="daily_batch_load_db",
                progress=80,
                trade_date=trade_date,
                message=f"批量入库 {trade_date} 行情数据",
                total=1,
                current=0,
                record_count=int(len(records)),
            )
            db_record_count, db_stock_count = self._load_records_to_db(records)

            self.manifest_service.complete_batch(
                batch,
                status="completed",
                record_count=len(records),
                stock_count=frame["code"].nunique(),
                storage_path=str(snapshot_path),
                file_size_bytes=file_size,
                checksum=checksum,
                meta={"mode": "daily_batch", "db_record_count": db_record_count},
            )
            manifest = self.manifest_service.upsert_manifest(
                trade_date=trade_day,
                status="loaded",
                source=source,
                batch_id=batch.id,
                storage_path=str(snapshot_path),
                record_count=len(records),
                stock_count=int(frame["code"].nunique()),
                db_record_count=db_record_count,
                db_stock_count=db_stock_count,
                file_size_bytes=file_size,
                checksum=checksum,
                meta={"mode": "daily_batch"},
                fetched_at=batch.started_at,
                loaded_to_db_at=batch.completed_at,
            )
            result = {
                "ok": True,
                "trade_date": trade_date,
                "record_count": manifest.record_count,
                "stock_count": manifest.stock_count,
                "db_record_count": manifest.db_record_count,
                "db_stock_count": manifest.db_stock_count,
                "storage_path": manifest.storage_path,
                "raw_csv_synced": sync_raw_csv,
            }
            self._emit_progress(
                progress_callback,
                stage="daily_batch_completed",
                progress=100,
                trade_date=trade_date,
                message=f"{trade_date} 批量刷新完成",
                total=1,
                current=1,
                updated_count=int(manifest.db_stock_count or manifest.stock_count or 0),
                record_count=int(manifest.record_count or 0),
                db_record_count=int(manifest.db_record_count or 0),
                db_stock_count=int(manifest.db_stock_count or 0),
            )
            return result
        except Exception as exc:
            logger.exception("按交易日抓取失败: %s", exc)
            self.manifest_service.complete_batch(
                batch,
                status="failed",
                error_message=str(exc),
                meta={"mode": "daily_batch"},
            )
            self.manifest_service.upsert_manifest(
                trade_date=trade_day,
                status="failed",
                source=source,
                batch_id=batch.id,
                meta={"mode": "daily_batch", "error": str(exc)},
            )
            self._emit_progress(
                progress_callback,
                stage="failed",
                progress=100,
                trade_date=trade_date,
                message=f"{trade_date} 批量刷新失败: {exc}",
                total=1,
                current=1,
                failed_count=1,
            )
            raise
