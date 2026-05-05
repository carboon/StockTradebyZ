#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]


def _load_missing_codes(conn) -> list[str]:
    rows = conn.execute(text("""
        SELECT s.code
        FROM stocks s
        LEFT JOIN (SELECT DISTINCT code FROM stock_daily) d ON s.code = d.code
        WHERE d.code IS NULL
        ORDER BY s.code
    """))
    return [str(row[0]).zfill(6) for row in rows]


def _iter_csv_rows(csv_path: Path, code: str):
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_text = str(row.get("date", "")).strip()
            if not date_text:
                continue
            yield (
                code,
                date_text,
                row.get("open", ""),
                row.get("close", ""),
                row.get("high", ""),
                row.get("low", ""),
                row.get("volume", ""),
            )


def main() -> int:
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.database import engine

    raw_dir = ROOT / "data" / "raw"
    if not raw_dir.exists():
        print(f"raw data dir not found: {raw_dir}")
        return 1

    with engine.begin() as conn:
        missing_codes = _load_missing_codes(conn)

    csv_codes = {path.stem.zfill(6): path for path in raw_dir.glob("*.csv")}
    importable_codes = [code for code in missing_codes if code in csv_codes]
    missing_csv_codes = [code for code in missing_codes if code not in csv_codes]

    print(f"missing_codes_in_db={len(missing_codes)}")
    print(f"importable_codes={len(importable_codes)}")
    print(f"missing_csv_codes={len(missing_csv_codes)}")
    if missing_csv_codes:
        print(f"missing_csv_sample={missing_csv_codes[:20]}")

    if not importable_codes:
        return 0

    total_rows = 0
    imported_codes = 0
    batch_size = 100

    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("""
                CREATE TEMP TABLE tmp_stock_daily_import (
                    code TEXT NOT NULL,
                    trade_date DATE NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    close DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    volume DOUBLE PRECISION NOT NULL
                )
            """)
        raw.commit()

        for start in range(0, len(importable_codes), batch_size):
            chunk = importable_codes[start:start + batch_size]
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            chunk_rows = 0
            for code in chunk:
                csv_path = csv_codes[code]
                for item in _iter_csv_rows(csv_path, code):
                    writer.writerow(item)
                    chunk_rows += 1
            if chunk_rows == 0:
                continue

            buf.seek(0)
            with raw.cursor() as cur:
                cur.execute("TRUNCATE TABLE tmp_stock_daily_import")
                cur.copy_expert(
                    """
                    COPY tmp_stock_daily_import
                    (code, trade_date, open, close, high, low, volume)
                    FROM STDIN WITH (FORMAT CSV)
                    """,
                    buf,
                )
                cur.execute("""
                    INSERT INTO stock_daily (code, trade_date, open, close, high, low, volume, created_at)
                    SELECT code, trade_date, open, close, high, low, volume, NOW()
                    FROM tmp_stock_daily_import
                    ON CONFLICT (code, trade_date) DO UPDATE SET
                        open = EXCLUDED.open,
                        close = EXCLUDED.close,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        volume = EXCLUDED.volume
                """)
            raw.commit()
            total_rows += chunk_rows
            imported_codes += len(chunk)
            print(
                f"imported_codes_progress={imported_codes}/{len(importable_codes)} "
                f"batch_rows={chunk_rows} total_rows={total_rows}"
            )
    finally:
        raw.close()

    print(f"done_importable_codes={imported_codes}")
    print(f"done_total_rows={total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
