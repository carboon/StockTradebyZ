from datetime import datetime
from typing import Any
from unittest.mock import patch

from app.services.intraday_analysis_service import ASIA_SHANGHAI


def test_late_session_status_returns_window_state(test_client_with_db: Any) -> None:
    fake_now = datetime(2026, 5, 8, 14, 35, tzinfo=ASIA_SHANGHAI)

    with patch("app.services.late_session_screen_service.LateSessionScreenService.now_shanghai", return_value=fake_now):
        response = test_client_with_db.get("/api/v1/analysis/late-session/status")

    assert response.status_code == 200
    data = response.json()
    assert data["window_open"] is True
    assert data["has_data"] is False
    assert data["items"] == []


def test_late_session_add_watchlist_empty_payload(test_client_with_db: Any) -> None:
    response = test_client_with_db.post("/api/v1/analysis/late-session/add-watchlist", json={"codes": []})

    assert response.status_code == 200
    assert response.json()["added_count"] == 0
