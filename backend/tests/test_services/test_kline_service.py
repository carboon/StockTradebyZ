from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, close_db_session
from app.models import Stock, StockDaily
from app.services.daily_data_service import DailyDataService
from app.services.kline_service import save_daily_data


def _build_fk_session() -> tuple[Session, object]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    return session, engine


def test_save_daily_data_creates_parent_stock_row_when_missing() -> None:
    db, engine = _build_fk_session()
    try:
        df = pd.DataFrame(
            [
                {"date": "2024-01-02", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 1000},
                {"date": "2024-01-03", "open": 11, "close": 10.5, "high": 11.5, "low": 10, "volume": 800},
            ]
        )

        saved = save_daily_data(db, "000069", df)

        assert saved == 2
        stock = db.query(Stock).filter(Stock.code == "000069").one()
        rows = (
            db.query(StockDaily)
            .filter(StockDaily.code == "000069")
            .order_by(StockDaily.trade_date)
            .all()
        )
        assert stock.market == "SZ"
        assert [row.trade_date for row in rows] == [date(2024, 1, 2), date(2024, 1, 3)]
    finally:
        close_db_session(db)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_daily_data_service_normalizes_code_and_creates_parent_stock_row(monkeypatch) -> None:
    db, engine = _build_fk_session()
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.services.daily_data_service.SessionLocal", TestingSessionLocal)

    try:
        df = pd.DataFrame(
            [
                {
                    "code": "000069.SZ",
                    "trade_date": date(2024, 1, 2),
                    "open": 10,
                    "high": 12,
                    "low": 9,
                    "close": 11,
                    "volume": 1000,
                }
            ]
        )

        saved = DailyDataService(token="test-token").save_daily_data(df)

        assert saved == 1
        stock = db.query(Stock).filter(Stock.code == "000069").one()
        row = db.query(StockDaily).filter(StockDaily.code == "000069").one()
        assert stock.market == "SZ"
        assert row.trade_date == date(2024, 1, 2)
    finally:
        close_db_session(db)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
