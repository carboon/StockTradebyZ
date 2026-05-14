from __future__ import annotations

import os
import statistics
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Callable
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

if (
    os.environ.get("STOCKTRADE_BENCHMARK_BOOTSTRAPPED") != "1"
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
):
    env = dict(os.environ)
    env["STOCKTRADE_BENCHMARK_BOOTSTRAPPED"] = "1"
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]], env)

pythonpath_entries = [entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry]
for required_path in (str(ROOT), str(BACKEND)):
    if required_path not in pythonpath_entries:
        pythonpath_entries.append(required_path)
    if required_path not in sys.path:
        sys.path.insert(0, required_path)
if pythonpath_entries:
    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

os.environ["PYTEST_RUNNING"] = "1"

from app.auth import hash_password
from app.cache import cache
from app.database import Base, get_db
from app.main import app
from app.models import Candidate, Stock, StockAnalysis, StockDaily, User, Watchlist

def build_test_database_url() -> str:
    return f"sqlite:///file:perf_db_{uuid.uuid4().hex}?mode=memory&cache=shared"


@contextmanager
def benchmark_client():
    test_database_url = build_test_database_url()
    engine = create_engine(
        test_database_url,
        connect_args={"check_same_thread": False, "uri": True},
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = testing_session_local()

    test_user = User(
        username="perfuser",
        hashed_password=hash_password("perfpass123"),
        display_name="Perf User",
        role="user",
        is_active=True,
        daily_quota=1000,
    )
    db.add(test_user)
    db.commit()
    db.refresh(test_user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    from app.api import deps

    def mock_get_current_user():
        return test_user

    def mock_require_user():
        return test_user

    def mock_get_admin_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = mock_get_current_user
    app.dependency_overrides[deps.require_user] = mock_require_user
    app.dependency_overrides[deps.get_admin_user] = mock_get_admin_user

    try:
        with TestClient(app) as client:
            yield client, db, test_user
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def seed_data(db: Session, user_id: int) -> None:
    stocks = [
        Stock(code="600000", name="浦发银行", market="SH", industry="银行"),
        Stock(code="000001", name="平安银行", market="SZ", industry="银行"),
        Stock(code="600036", name="招商银行", market="SH", industry="银行"),
        Stock(code="600519", name="贵州茅台", market="SH", industry="白酒"),
        Stock(code="000858", name="五粮液", market="SZ", industry="白酒"),
    ]
    db.add_all(stocks)
    db.flush()

    today = date(2026, 5, 6)

    for idx, stock in enumerate(stocks[:3], start=1):
        db.add(
            Watchlist(
                user_id=user_id,
                code=stock.code,
                add_reason=f"reason-{idx}",
                entry_price=10.0 + idx,
                position_ratio=0.2 + idx * 0.1,
                priority=idx,
                is_active=True,
            )
        )
        db.add(
            StockAnalysis(
                code=stock.code,
                trade_date=today,
                analysis_type="daily_b1",
                strategy_version="v1",
                close_price=10.5 + idx,
                verdict="PASS",
                score=4.2,
                signal_type="trend_start",
                b1_passed=True,
                kdj_j=21.5,
                zx_long_pos=True,
                weekly_ma_aligned=True,
                volume_healthy=True,
            )
        )

    for stock in stocks:
        for offset in range(180):
            trade_day = today - timedelta(days=offset)
            base = 10 + (offset % 20) * 0.1
            db.add(
                StockDaily(
                    code=stock.code,
                    trade_date=trade_day,
                    open=base,
                    close=base + 0.2,
                    high=base + 0.5,
                    low=base - 0.3,
                    volume=1_000_000 + offset * 1000,
                )
            )

    for idx, stock in enumerate(stocks, start=1):
        db.add(
            Candidate(
                pick_date=today,
                code=stock.code,
                strategy="b1",
                close_price=20.0 + idx,
                turnover=3.0 + idx,
                b1_passed=True,
                kdj_j=10.0 + idx,
            )
        )

    db.commit()


def measure(label: str, fn: Callable[[], None], iterations: int = 20) -> dict[str, float]:
    samples_ms: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - started) * 1000)
    return {
        "label": label,
        "avg_ms": round(statistics.mean(samples_ms), 2),
        "p95_ms": round(sorted(samples_ms)[max(0, int(iterations * 0.95) - 1)], 2),
        "min_ms": round(min(samples_ms), 2),
        "max_ms": round(max(samples_ms), 2),
    }


def main() -> None:
    with benchmark_client() as (client, db, test_user):
        seed_data(db, test_user.id)

        benchmark_results: list[dict[str, float]] = []

        scenarios = [
            ("watchlist", lambda: client.get("/api/v1/watchlist/")),
            ("candidates", lambda: client.get("/api/v1/analysis/tomorrow-star/candidates?limit=100")),
            ("kline", lambda: client.post("/api/v1/stock/kline", json={"code": "600000", "days": 120, "include_weekly": True})),
            ("search", lambda: client.get("/api/v1/stock/search?q=银行&limit=10")),
        ]

        for label, fn in scenarios:
            cache.clear()
            cold = measure(f"{label}:cold", fn, iterations=1)
            warm = measure(f"{label}:warm", fn, iterations=20)
            benchmark_results.extend([cold, warm])

        cache.clear()
        with patch("app.api.analysis.TushareService.is_trade_date_data_ready", return_value=True), patch(
            "app.services.market_service.market_service"
        ) as mock_market_service:
            mock_market_service.token = "test-token"
            mock_market_service.get_latest_trade_date.return_value = date(2026, 5, 6)
            mock_market_service.get_local_latest_date.return_value = date(2026, 5, 6)
            freshness_cold = measure(
                "freshness:cold",
                lambda: client.get("/api/v1/analysis/tomorrow-star/freshness"),
                iterations=1,
            )
            freshness_warm = measure(
                "freshness:warm",
                lambda: client.get("/api/v1/analysis/tomorrow-star/freshness"),
                iterations=20,
            )
            benchmark_results.extend([freshness_cold, freshness_warm])

        print("API performance benchmark results (ms)")
        for item in benchmark_results:
            print(
                f"{item['label']:18} avg={item['avg_ms']:7.2f} "
                f"p95={item['p95_ms']:7.2f} min={item['min_ms']:7.2f} max={item['max_ms']:7.2f}"
            )


if __name__ == "__main__":
    main()
