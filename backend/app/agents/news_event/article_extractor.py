"""Article extractor - fetches full article content from URLs."""
from __future__ import annotations

import logging
from typing import Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class ArticleExtractor:
    """提取网页正文、标题、发布时间。第一期使用搜索结果摘要，第二期补充全文抓取。"""

    def __init__(self) -> None:
        self._timeout = settings.news_agent_article_fetch_timeout_seconds

    def extract(self, url: str) -> Optional[dict[str, str]]:
        if not url:
            return None

        try:
            response = requests.get(
                url,
                timeout=self._timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.info("ArticleExtractor fetch failed for %s: %s", url, exc)
            return None

        html = response.text
        title = self._extract_title(html)
        text = self._extract_text(html)

        return {
            "title": title or "",
            "content": text[:5000] if text else "",
            "url": url,
        }

    @staticmethod
    def _extract_title(html: str) -> str:
        import re
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            return title
        return ""

    @staticmethod
    def _extract_text(html: str) -> str:
        import re
        for tag in ["script", "style", "nav", "footer", "header", "aside"]:
            html = re.sub(
                rf"<{tag}[^>]*>.*?</{tag}>", "", html,
                flags=re.IGNORECASE | re.DOTALL,
            )
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"&[a-z]+;", " ", text, flags=re.IGNORECASE)
        return text.strip()


article_extractor = ArticleExtractor()
