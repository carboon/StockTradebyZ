"""
Daily Batch Update Service
~~~~~~~~~~~~~~~~~~~~~~~~~~
按交易日批量抓取全市场日线，先落地日分片文件，再批量入库并更新 manifest。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Any, Callable

import pandas as pd
from sqlalchemy import select, func, distinct, delete
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import StockDaily
from app.services.daily_data_service import bulk_upsert_stock_daily
from app.services.raw_data_manifest_service import RawDataManifestService
from app.services.realtime_daily_bar_service import RealtimeDailyBarService
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
        self.realtime_daily_bar_service = RealtimeDailyBarService()

    def __enter__(self) -> "DailyBatchUpdateService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._owns_session:
            self.db.close()

    def _daily_partition_path(self, trade_date: str) -> Path:
        return ROOT / "data" / "raw_daily" / f"{trade_date}.jsonl"

    def _get_recent_trade_dates(self, trade_date: date, limit: int = 5) -> list[date]:
        rows = self.db.execute(
            select(StockDaily.trade_date)
            .where(StockDaily.trade_date < trade_date)
            .distinct()
            .order_by(StockDaily.trade_date.desc())
            .limit(limit)
        ).scalars().all()
        return [item for item in rows if item is not None]

    def _fill_missing_volume_ratio_from_history(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or "code" not in frame.columns or "trade_date" not in frame.columns:
            return frame

        working = frame.copy()
        if "volume_ratio" not in working.columns:
            working["volume_ratio"] = pd.NA

        missing_mask = working["volume_ratio"].isna()
        if not bool(missing_mask.any()):
            return working

        trade_date_value = working["trade_date"].iloc[0]
        if not isinstance(trade_date_value, date):
            trade_date_value = pd.to_datetime(trade_date_value).date()

        previous_trade_dates = self._get_recent_trade_dates(trade_date_value, limit=5)
        if not previous_trade_dates:
            return working

        codes = sorted(
            {
                str(code).zfill(6)
                for code in working.loc[missing_mask, "code"].dropna().astype(str).tolist()
            }
        )
        if not codes:
            return working

        rows = self.db.execute(
            select(StockDaily.code, StockDaily.volume)
            .where(
                StockDaily.code.in_(codes),
                StockDaily.trade_date.in_(previous_trade_dates),
            )
        ).all()

        avg_volume_by_code: dict[str, float] = {}
        history_volume_by_code: dict[str, list[float]] = {}
        for code, volume in rows:
            if volume is None:
                continue
            numeric_volume = float(volume)
            if numeric_volume <= 0:
                continue
            history_volume_by_code.setdefault(str(code).zfill(6), []).append(numeric_volume)

        for code, volumes in history_volume_by_code.items():
            if volumes:
                avg_volume_by_code[code] = sum(volumes) / len(volumes)

        filled_count = 0
        for idx in working.index[missing_mask]:
            code = str(working.at[idx, "code"]).zfill(6)
            avg_volume = avg_volume_by_code.get(code)
            current_volume = pd.to_numeric(working.at[idx, "volume"], errors="coerce")
            if avg_volume in (None, 0) or pd.isna(current_volume) or float(current_volume) <= 0:
                continue
            working.at[idx, "volume_ratio"] = round(float(current_volume) / avg_volume, 4)
            filled_count += 1

        if filled_count > 0:
            logger.info(
                "本地回填量比 trade_date=%s filled=%s/%s prev_trade_days=%s",
                trade_date_value.isoformat(),
                filled_count,
                int(missing_mask.sum()),
                len(previous_trade_dates),
            )
        return working

    def fetch_trade_date_snapshot(self, trade_date: str) -> pd.DataFrame:
        normalized = trade_date.replace("-", "")
        acquire_tushare_slot("daily")
        frame = self.tushare_service.pro.daily(trade_date=normalized)
        if frame is None or frame.empty:
            return self._fetch_realtime_trade_date_snapshot(trade_date)

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
        if daily_basic is None or daily_basic.empty:
            daily_basic = pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
                    "turnover_rate",
                    "turnover_rate_f",
                    "volume_ratio",
                    "free_share",
                    "circ_mv",
                ]
            )
        acquire_tushare_slot("moneyflow")
        moneyflow = self.tushare_service.pro.moneyflow(
            trade_date=normalized,
            fields=(
                "ts_code,trade_date,buy_sm_amount,sell_sm_amount,"
                "buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,"
                "buy_elg_amount,sell_elg_amount,net_mf_amount"
            ),
        )
        if moneyflow is None or moneyflow.empty:
            moneyflow = pd.DataFrame(
                columns=[
                    "ts_code",
                    "trade_date",
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
            )
        frame = frame.merge(daily_basic, on=["ts_code", "trade_date"], how="left")
        frame = frame.merge(moneyflow, on=["ts_code", "trade_date"], how="left")
        frame["code"] = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        frame = self._fill_missing_volume_ratio_from_history(frame)
        return frame.sort_values(["trade_date", "code"]).reset_index(drop=True)

    def _load_realtime_target_codes(self) -> list[str]:
        latest_trade_date = self.db.execute(select(func.max(StockDaily.trade_date))).scalar()
        if latest_trade_date is None:
            return []
        rows = self.db.execute(
            select(StockDaily.code)
            .where(StockDaily.trade_date == latest_trade_date)
            .order_by(StockDaily.code.asc())
        ).scalars().all()
        return [str(code).zfill(6) for code in rows if code]

    def _fetch_realtime_trade_date_snapshot(self, trade_date: str) -> pd.DataFrame:
        trade_day = datetime.fromisoformat(trade_date).date()
        codes = self._load_realtime_target_codes()
        if not codes:
            logger.warning("实时日K兜底失败：本地无可参考股票池 trade_date=%s", trade_date)
            return pd.DataFrame()
        bars = self.realtime_daily_bar_service.fetch_bars(codes, trade_date=trade_day)
        if not bars:
            logger.warning("实时日K兜底失败：腾讯行情无完整返回 trade_date=%s target_count=%s", trade_date, len(codes))
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        for code in sorted(bars):
            bar = bars[code]
            if bar.open is None or bar.close is None or bar.high is None or bar.low is None or bar.volume is None:
                continue
            if bar.open <= 0 or bar.close <= 0 or bar.high <= 0 or bar.low <= 0 or bar.volume <= 0:
                continue
            market = "SH" if code.startswith("6") else ("BJ" if code.startswith(("4", "8", "9")) else "SZ")
            rows.append(
                {
                    "ts_code": f"{code}.{market}",
                    "trade_date": trade_day,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "turnover_rate": bar.turnover_rate,
                    "turnover_rate_f": None,
                    "volume_ratio": bar.volume_ratio,
                    "free_share": None,
                    "circ_mv": (bar.circ_mv / 10_000.0) if bar.circ_mv is not None else None,
                    "buy_sm_amount": None,
                    "sell_sm_amount": None,
                    "buy_md_amount": None,
                    "sell_md_amount": None,
                    "buy_lg_amount": None,
                    "sell_lg_amount": None,
                    "buy_elg_amount": None,
                    "sell_elg_amount": None,
                    "net_mf_amount": None,
                    "code": code,
                    "data_source": "tencent_quote",
                }
            )

        frame = pd.DataFrame(rows)
        if frame.empty:
            logger.warning("实时日K兜底失败：腾讯行情无有效 OHLCV trade_date=%s target_count=%s", trade_date, len(codes))
            return frame
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

    def _sync_raw_csv_from_db(
        self,
        *,
        codes: list[str],
        end_date: date,
        min_history_days: int = 260,
    ) -> dict[str, int]:
        """Rewrite raw CSV from DB so selector inputs keep enough warmup history."""
        normalized_codes = sorted({str(code or "").zfill(6) for code in codes if str(code or "").strip()})
        if not normalized_codes:
            return {"updated_files": 0, "synced_rows": 0}

        start_date = end_date - timedelta(days=max(365, int(min_history_days * 2)))
        rows = (
            self.db.query(
                StockDaily.code,
                StockDaily.trade_date,
                StockDaily.open,
                StockDaily.close,
                StockDaily.high,
                StockDaily.low,
                StockDaily.volume,
                StockDaily.turnover_rate,
                StockDaily.turnover_rate_f,
                StockDaily.volume_ratio,
                StockDaily.free_share,
                StockDaily.circ_mv,
                StockDaily.buy_sm_amount,
                StockDaily.sell_sm_amount,
                StockDaily.buy_md_amount,
                StockDaily.sell_md_amount,
                StockDaily.buy_lg_amount,
                StockDaily.sell_lg_amount,
                StockDaily.buy_elg_amount,
                StockDaily.sell_elg_amount,
                StockDaily.net_mf_amount,
            )
            .filter(
                StockDaily.code.in_(normalized_codes),
                StockDaily.trade_date >= start_date,
                StockDaily.trade_date <= end_date,
            )
            .order_by(StockDaily.code.asc(), StockDaily.trade_date.asc(), StockDaily.id.asc())
            .yield_per(10000)
        )

        raw_dir = ROOT / settings.raw_data_dir
        raw_dir.mkdir(parents=True, exist_ok=True)

        updated_files = 0
        synced_rows = 0
        current_code: str | None = None
        current_rows: list[dict[str, Any]] = []

        def flush_current() -> None:
            nonlocal updated_files, synced_rows, current_code, current_rows
            if current_code is None or not current_rows:
                return
            frame = pd.DataFrame(current_rows)
            frame = frame[columns].copy()
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            frame.to_csv(raw_dir / f"{current_code}.csv", index=False)
            updated_files += 1
            synced_rows += len(frame.index)
            current_rows = []

        columns = [
            "date",
            "open",
            "close",
            "high",
            "low",
            "volume",
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
            "code",
        ]

        for row in rows:
            code = str(row.code).zfill(6)
            if current_code is None:
                current_code = code
            elif code != current_code:
                flush_current()
                current_code = code
            current_rows.append(
                {
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
                    "code": code,
                }
            )

        flush_current()

        return {"updated_files": updated_files, "synced_rows": synced_rows}

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

    def _delete_stale_records_for_trade_date(self, trade_day: date, codes: list[str]) -> int:
        normalized_codes = sorted({str(code or "").zfill(6) for code in codes if str(code or "").strip()})
        if not normalized_codes:
            return 0

        stmt = delete(StockDaily).where(
            StockDaily.trade_date == trade_day,
            StockDaily.code.not_in(normalized_codes),
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return int(result.rowcount or 0)

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
            db_record_count, _ = self._load_records_to_db(records)
            snapshot_codes = [str(code).zfill(6) for code in frame["code"].dropna().astype(str).unique().tolist()]
            stale_deleted_count = self._delete_stale_records_for_trade_date(trade_day, snapshot_codes)
            db_stock_count = int(
                self.db.execute(
                    select(func.count(distinct(StockDaily.code))).where(StockDaily.trade_date == trade_day)
                ).scalar()
                or 0
            )
            raw_csv_sync_result = {"updated_files": 0, "synced_rows": 0}
            if sync_raw_csv:
                raw_csv_sync_result = self._sync_raw_csv_from_db(
                    codes=snapshot_codes,
                    end_date=trade_day,
                )

            self.manifest_service.complete_batch(
                batch,
                status="completed",
                record_count=len(records),
                stock_count=frame["code"].nunique(),
                storage_path=str(snapshot_path),
                file_size_bytes=file_size,
                checksum=checksum,
                meta={
                    "mode": "daily_batch",
                    "db_record_count": db_record_count,
                    "stale_deleted_count": stale_deleted_count,
                },
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
                meta={"mode": "daily_batch", "stale_deleted_count": stale_deleted_count},
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
                "raw_csv_updated_files": raw_csv_sync_result["updated_files"],
                "raw_csv_synced_rows": raw_csv_sync_result["synced_rows"],
                "stale_deleted_count": stale_deleted_count,
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
