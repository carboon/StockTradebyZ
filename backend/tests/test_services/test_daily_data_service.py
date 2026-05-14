from __future__ import annotations

from datetime import date
from pathlib import Path

from app.services.daily_data_service import DailyDataService


class _FakeCursor:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.copy_sql: str | None = None
        self.copy_payload: str | None = None
        self.rowcount = 3

    def execute(self, sql: str) -> None:
        self.executed_sql.append(" ".join(sql.split()))

    def copy_expert(self, sql: str, file_obj) -> None:  # type: ignore[no-untyped-def]
        self.copy_sql = " ".join(sql.split())
        self.copy_payload = file_obj.read()


class _FakeRawConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor


class _FakeConnectionWrapper:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.connection = _FakeRawConnection(cursor)


class _FakeSession:
    def __init__(self, cursor: _FakeCursor | None = None) -> None:
        self._cursor = cursor
        self.commit_called = False

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def connection(self) -> _FakeConnectionWrapper:
        if self._cursor is None:
            raise AssertionError("unexpected connection() call")
        return _FakeConnectionWrapper(self._cursor)

    def commit(self) -> None:
        self.commit_called = True


def test_batch_import_csv_fast_commits_parent_stocks_before_copy(tmp_path: Path, monkeypatch) -> None:
    csv_path = tmp_path / "000001.csv"
    csv_path.write_text(
        "trade_date,open,close,high,low,volume\n"
        "2024-01-02,10,11,12,9,1000\n",
        encoding="utf-8",
    )

    ensure_session = _FakeSession()
    copy_cursor = _FakeCursor()
    copy_session = _FakeSession(cursor=copy_cursor)
    sessions = [ensure_session, copy_session]
    ensured_codes: list[str] = []

    def _fake_session_local() -> _FakeSession:
        if not sessions:
            raise AssertionError("unexpected SessionLocal() call")
        return sessions.pop(0)

    def _fake_ensure_stock_row(db, code: str) -> None:  # type: ignore[no-untyped-def]
        ensured_codes.append(code)

    monkeypatch.setattr("app.services.daily_data_service.SessionLocal", _fake_session_local)
    monkeypatch.setattr("app.services.daily_data_service.ensure_stock_row", _fake_ensure_stock_row)

    result = DailyDataService(token="test-token").batch_import_csv_fast(tmp_path)

    assert result["success"] is True
    assert result["imported"] == 1
    assert ensured_codes == ["000001"]
    assert ensure_session.commit_called is True
    assert copy_session.commit_called is True
    assert copy_cursor.copy_sql is not None
    assert "COPY temp_stock_daily" in copy_cursor.copy_sql
    assert copy_cursor.copy_payload is not None
    assert "000001,2024-01-02,10,11,12,9,1000" in copy_cursor.copy_payload
    assert any("INSERT INTO stock_daily" in sql for sql in copy_cursor.executed_sql)


def test_batch_import_from_csv_uses_filename_code_and_deduplicates_dates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "000001.csv"
    csv_path.write_text(
        "code,date,open,close,high,low,volume\n"
        ",2024-01-02,10,11,12,9,1000\n"
        "wrong,2024-01-02,20,21,22,19,2000\n",
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _fake_session_local() -> _FakeSession:
        return _FakeSession()

    def _fake_bulk_upsert(db, records, batch_size=1000):  # type: ignore[no-untyped-def]
        captured["records"] = records
        return {"inserted": len(records), "failed": 0}

    monkeypatch.setattr("app.services.daily_data_service.SessionLocal", _fake_session_local)
    monkeypatch.setattr("app.services.daily_data_service.bulk_upsert_stock_daily", _fake_bulk_upsert)

    result = DailyDataService(token="test-token").batch_import_from_csv(tmp_path)

    assert result["success"] is True
    assert result["total_records"] == 1
    assert captured["records"] == [
        {
            "code": "000001",
            "trade_date": date(2024, 1, 2),
            "open": 20.0,
            "close": 21.0,
            "high": 22.0,
            "low": 19.0,
            "volume": 2000.0,
        }
    ]


def test_batch_import_csv_fast_uses_filename_code_and_deduplicates_dates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    csv_path = tmp_path / "000001.csv"
    csv_path.write_text(
        "code,trade_date,open,close,high,low,volume\n"
        ",2024-01-02,10,11,12,9,1000\n"
        "wrong,2024-01-02,20,21,22,19,2000\n",
        encoding="utf-8",
    )

    ensure_session = _FakeSession()
    copy_cursor = _FakeCursor()
    copy_session = _FakeSession(cursor=copy_cursor)
    sessions = [ensure_session, copy_session]
    ensured_codes: list[str] = []

    def _fake_session_local() -> _FakeSession:
        if not sessions:
            raise AssertionError("unexpected SessionLocal() call")
        return sessions.pop(0)

    def _fake_ensure_stock_row(db, code: str) -> None:  # type: ignore[no-untyped-def]
        ensured_codes.append(code)

    monkeypatch.setattr("app.services.daily_data_service.SessionLocal", _fake_session_local)
    monkeypatch.setattr("app.services.daily_data_service.ensure_stock_row", _fake_ensure_stock_row)

    result = DailyDataService(token="test-token").batch_import_csv_fast(tmp_path)

    assert result["success"] is True
    assert ensured_codes == ["000001"]
    assert copy_cursor.copy_payload is not None
    assert "000001,2024-01-02,20,21,22,19,2000" in copy_cursor.copy_payload
    assert "wrong,2024-01-02" not in copy_cursor.copy_payload
