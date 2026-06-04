"""Tests for SearXNG search provider."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.search.searxng_search_service import SearXNGSearchProvider


def test_health_check_reports_403_configuration_error():
    provider = SearXNGSearchProvider(base_url="http://searxng.local")
    response = MagicMock()
    response.status_code = 403

    with patch("app.services.search.searxng_search_service.requests.get", return_value=response):
        assert provider.health_check(force=True) is False

    assert "403" in provider.last_error


def test_search_returns_empty_when_health_check_fails():
    provider = SearXNGSearchProvider(base_url="http://searxng.local")
    with patch.object(provider, "health_check", return_value=False):
        assert provider.search("英伟达") == []
