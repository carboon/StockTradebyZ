"""
Raw Data Manifest Service
~~~~~~~~~~~~~~~~~~~~~~~~~
维护原始数据抓取批次和按交易日清单，供任务和状态页快速读取。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RawDataBatch, RawDataManifest
from app.time_utils import utc_now


class RawDataManifestService:
    """原始数据清单服务。"""

    def __init__(self, db: Session):
        self.db = db

    def create_batch(
        self,
        *,
        batch_type: str,
        trade_date: Optional[date],
        source: Optional[str],
        storage_path: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> RawDataBatch:
        batch = RawDataBatch(
            batch_type=batch_type,
            trade_date=trade_date,
            source=source,
            storage_path=storage_path,
            meta_json=meta or {},
            status="running",
            started_at=utc_now(),
        )
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def complete_batch(
        self,
        batch: RawDataBatch,
        *,
        status: str,
        record_count: int = 0,
        stock_count: int = 0,
        storage_path: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        checksum: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> RawDataBatch:
        batch.status = status
        batch.record_count = int(record_count or 0)
        batch.stock_count = int(stock_count or 0)
        batch.storage_path = storage_path or batch.storage_path
        batch.file_size_bytes = file_size_bytes
        batch.checksum = checksum
        batch.error_message = error_message
        batch.meta_json = meta or batch.meta_json
        batch.completed_at = utc_now()
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def upsert_manifest(
        self,
        *,
        trade_date: date,
        status: str,
        source: Optional[str],
        batch_id: Optional[int] = None,
        storage_path: Optional[str] = None,
        record_count: int = 0,
        stock_count: int = 0,
        db_record_count: Optional[int] = None,
        db_stock_count: Optional[int] = None,
        file_size_bytes: Optional[int] = None,
        checksum: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        fetched_at: Optional[datetime] = None,
        loaded_to_db_at: Optional[datetime] = None,
    ) -> RawDataManifest:
        manifest = self.db.execute(
            select(RawDataManifest).where(RawDataManifest.trade_date == trade_date)
        ).scalar_one_or_none()

        if manifest is None:
            manifest = RawDataManifest(trade_date=trade_date)
            self.db.add(manifest)

        manifest.status = status
        manifest.source = source
        manifest.batch_id = batch_id
        manifest.storage_path = storage_path
        manifest.record_count = int(record_count or 0)
        manifest.stock_count = int(stock_count or 0)
        manifest.db_record_count = int(db_record_count or manifest.db_record_count or 0)
        manifest.db_stock_count = int(db_stock_count or manifest.db_stock_count or 0)
        manifest.file_size_bytes = file_size_bytes
        manifest.checksum = checksum
        manifest.meta_json = meta or manifest.meta_json
        manifest.fetched_at = fetched_at or manifest.fetched_at
        manifest.loaded_to_db_at = loaded_to_db_at or manifest.loaded_to_db_at
        self.db.commit()
        self.db.refresh(manifest)
        return manifest

    def get_latest_manifest(self) -> Optional[RawDataManifest]:
        return self.db.execute(
            select(RawDataManifest)
            .order_by(RawDataManifest.trade_date.desc(), RawDataManifest.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @staticmethod
    def calculate_file_checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def serialize_json_lines(records: list[dict[str, Any]], path: Path) -> tuple[int, int]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in records:
                handle.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        default=RawDataManifestService._json_default,
                    ) + "\n"
                )
        return len(records), path.stat().st_size
