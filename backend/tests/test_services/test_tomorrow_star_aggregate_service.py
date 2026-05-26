from datetime import date

from app.cache import cache
from app.models import Candidate, Stock
from app.services.tomorrow_star_aggregate_service import TomorrowStarAggregateCache


def test_tomorrow_star_aggregate_cache_hits_and_invalidates_on_candidate_change(db_session):
    cache.clear()

    service = TomorrowStarAggregateCache(db_session)
    payload = {
        "dates": ["2026-05-26"],
        "history": [],
        "window_status": None,
        "candidates": None,
        "results": None,
        "freshness": None,
        "generated_at": "2026-05-26T15:01:00",
        "cache_hit": False,
    }

    service.set(payload, candidate_limit=3000)
    cached = service.get(candidate_limit=3000)

    assert cached is not None
    assert cached["cache_hit"] is True
    assert cached["dates"] == ["2026-05-26"]

    db_session.add(Stock(code="000001", name="平安银行"))
    db_session.add(Candidate(pick_date=date(2026, 5, 26), code="000001", strategy="b1"))
    db_session.commit()

    assert service.get(candidate_limit=3000) is None
    cache.clear()
