from app.services.tomorrow_star_window_service import TomorrowStarWindowSummary
from app.services.view_prewarm_service import _serialize_window_summary


def test_serialize_window_summary_supports_to_dict():
    summary = TomorrowStarWindowSummary(
        window_size=120,
        latest_date="2026-05-19",
        ready_count=120,
        missing_count=0,
        running_count=0,
        failed_count=0,
        pending_count=0,
        items=[],
    )

    payload = _serialize_window_summary(summary)

    assert payload["window_size"] == 120
    assert payload["latest_date"] == "2026-05-19"
    assert payload["history"] == []
