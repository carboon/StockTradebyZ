"""News board API."""
from __future__ import annotations

import hashlib
import html
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
import requests
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.database import get_db
from app.schemas import (
    NewsBoardAnalyzeRequest,
    NewsBoardAnalyzeResponse,
    NewsBoardItem,
    NewsBoardItemsResponse,
    NewsBoardRelatedStock,
    NewsBoardSourceStatus,
)
from app.services.hot_news_aggregator_service import HotNewsAggregatorService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now

router = APIRouter()


CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("policy", ("政策", "国务院", "发改委", "工信部", "证监会", "央行", "财政部", "监管", "关税", "贸易", "商务部", "国家发展改革委")),
    ("weather", ("暴雨", "台风", "高温", "寒潮", "洪水", "地震", "极端天气", "灾害", "气象", "飓风", "干旱", "强对流", "大雾", "厄尔尼诺", "拉尼娜")),
    ("people", ("特朗普", "马斯克", "黄仁勋", "库克", "扎克伯格", "奥特曼", "贝森特", "鲍威尔", "Jensen", "Huang", "Musk", "Trump", "Powell")),
    ("us_market", ("美股", "纳指", "道指", "标普", "英伟达", "特斯拉", "苹果", "微软", "NVIDIA", "Tesla", "Nasdaq", "S&P")),
    ("price", ("涨停", "跌停", "大涨", "大跌", "异动", "放量", "拉升", "跳水", "股价")),
]
TUSHARE_NEWS_SOURCES: tuple[tuple[str, str], ...] = (
    ("xq", "雪球"),
    ("jinshi", "金十"),
    ("sina", "新浪财经"),
    ("jinrongjie", "金融界"),
    ("yicai", "第一财经"),
    ("10jqka", "同花顺"),
    ("cls", "财联社"),
    ("eastmoney", "东方财富"),
    ("wallstreetcn", "华尔街见闻"),
)
US_MARKET_SUMMARY_KEYWORDS = (
    "美股", "纳指", "道指", "标普", "纳斯达克", "英伟达", "特斯拉", "苹果", "微软",
    "NVIDIA", "Tesla", "Apple", "Microsoft", "Nasdaq", "S&P", "Dow Jones",
)

STOCK_HINTS: list[tuple[tuple[str, ...], tuple[str, str, str]]] = [
    (("AI", "人工智能", "算力", "服务器"), ("000977.SZ", "浪潮信息", "AI 服务器链条")),
    (("AI", "人工智能", "算力", "服务器", "液冷"), ("603019.SH", "中科曙光", "AI 算力基础设施")),
    (("英伟达", "黄仁勋", "GPU", "AI", "人工智能", "芯片"), ("300308.SZ", "中际旭创", "AI 光模块与高速互联")),
    (("英伟达", "黄仁勋", "GPU", "AI", "人工智能", "芯片"), ("300502.SZ", "新易盛", "AI 光模块与高速互联")),
    (("英伟达", "黄仁勋", "GPU", "AI", "人工智能", "芯片"), ("002463.SZ", "沪电股份", "AI 服务器 PCB")),
    (("半导体", "芯片", "国产替代", "自主可控"), ("688981.SH", "中芯国际", "国产半导体链条")),
    (("半导体", "芯片", "封测", "先进封装"), ("600584.SH", "长电科技", "半导体封测与先进封装")),
    (("Marvell", "迈威尔", "美满", "交换芯片", "网络芯片"), ("300308.SZ", "中际旭创", "高速互联与光模块")),
    (("Marvell", "迈威尔", "美满", "交换芯片", "网络芯片"), ("300394.SZ", "天孚通信", "光通信器件")),
    (("光模块", "CPO", "高速互联"), ("300308.SZ", "中际旭创", "光模块产业链")),
    (("特斯拉", "马斯克", "自动驾驶", "机器人"), ("002050.SZ", "三花智控", "汽车热管理与机器人执行器")),
    (("特斯拉", "马斯克", "自动驾驶", "机器人"), ("300124.SZ", "汇川技术", "工业自动化与机器人控制")),
    (("机器人", "执行器"), ("002050.SZ", "三花智控", "机器人执行器链条")),
    (("苹果", "Apple", "消费电子"), ("002475.SZ", "立讯精密", "消费电子与端侧 AI")),
    (("微软", "Microsoft", "云", "Azure", "AWS", "Amazon", "Meta", "Alphabet", "Gemini"), ("000977.SZ", "浪潮信息", "云计算资本开支与 AI 服务器")),
    (("极端天气", "暴雨", "洪水", "水利", "防汛"), ("002205.SZ", "国统股份", "水利与防汛主题")),
    (("保险", "灾害", "理赔"), ("601318.SH", "中国平安", "灾害理赔预期")),
    (("医药", "制药", "创新药", "FDA", "biotech", "pharma"), ("300759.SZ", "康龙化成", "创新药 CXO 链条")),
    (("医药", "制药", "创新药", "FDA", "biotech", "pharma"), ("603259.SH", "药明康德", "创新药 CXO 链条")),
]
INDUSTRY_HINTS: list[tuple[tuple[str, ...], tuple[str, str]]] = [
    (("AI", "人工智能", "算力", "GPU", "英伟达", "黄仁勋"), ("AI 算力", "服务器、PCB、光模块、液冷、国产芯片")),
    (("Marvell", "迈威尔", "美满", "网络芯片", "交换芯片"), ("高速互联", "光模块、光器件、交换芯片、数据中心网络")),
    (("半导体", "芯片", "先进封装", "封测"), ("半导体", "晶圆制造、封测、设备、材料")),
    (("特斯拉", "马斯克", "机器人", "自动驾驶"), ("机器人/智能汽车", "执行器、控制器、热管理、智能驾驶")),
    (("苹果", "Apple", "消费电子"), ("消费电子", "连接器、声学、结构件、端侧 AI")),
    (("暴雨", "洪水", "防汛", "台风", "厄尔尼诺", "气象"), ("天气灾害", "水利、防汛、农业、保险")),
    (("医药", "制药", "创新药", "FDA", "biotech", "pharma"), ("创新药", "CXO、创新药、医疗器械")),
    (("关税", "制裁", "地缘", "贸易", "监管"), ("地缘政策", "出口链、半导体国产替代、军工安全")),
]

NEGATIVE_KEYWORDS = ("利空", "下调", "处罚", "监管", "调查", "大跌", "跳水", "跌超", "下跌", "走低", "灾害", "理赔")
POSITIVE_KEYWORDS = ("利好", "上调", "突破", "扩张", "增长", "订单", "政策支持", "大涨", "拉升", "涨超", "上涨", "新高")
HTTP_HEADERS = {
    "User-Agent": "StockTradebyZ/2.0 contact=local-research@example.com",
    "Accept": "application/json,text/xml,application/xml,text/html,*/*",
}
SEC_COMPANIES = {
    "NVIDIA": "0001045810",
    "Tesla": "0001318605",
    "Marvell": "0001835632",
    "Microsoft": "0000789019",
    "Apple": "0000320193",
    "Amazon": "0001018724",
    "Meta": "0001326801",
    "Alphabet": "0001652044",
}
GOOGLE_NEWS_QUERIES = (
    '"Jensen Huang" OR "黄仁勋" AI OR Marvell OR NVIDIA',
    'Elon Musk OR Tesla AI robot geopolitics',
    'AI semiconductor CPO Marvell NVIDIA Microsoft Amazon Meta Alphabet',
    'pharmaceutical biotech FDA approval market',
    'Trump tariff China technology semiconductor',
    'China policy semiconductor AI pharmaceutical A-share',
)
GDELT_QUERIES = (
    '("Jensen Huang" OR "Elon Musk") (AI OR NVIDIA OR Tesla OR Marvell)',
    '(Trump OR White House) (tariff OR semiconductor OR China OR AI)',
)


@router.get("/items", response_model=NewsBoardItemsResponse)
def get_news_board_items(
    window_hours: int = Query(default=24, ge=1, le=72, description="消息窗口小时数"),
    limit: int = Query(default=80, ge=1, le=200, description="兼容参数；消息板块按时间窗口返回，不按该值截断"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> NewsBoardItemsResponse:
    del user
    now = utc_now()
    start_dt = now - timedelta(hours=window_hours)

    del db
    raw_items = _fetch_tushare_news_board_items(start_dt=start_dt, end_dt=now, limit=limit)
    items, duplicate_count = _normalize_news_items(raw_items, start_dt=start_dt, now=now, limit=limit)
    sources = _build_source_status(raw_items, items)
    message = None
    if not items:
        message = "未获取到最近 24H Tushare news 可展示消息；请检查 Tushare Token 和 news 接口权限。"

    return NewsBoardItemsResponse(
        window_hours=window_hours,
        generated_at=now,
        items=items,
        sources=sources,
        duplicate_count=duplicate_count,
        message=message,
    )


@router.post("/analyze", response_model=NewsBoardAnalyzeResponse)
def analyze_news_board_item(
    request: NewsBoardAnalyzeRequest,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> NewsBoardAnalyzeResponse:
    del db, user
    text = f"{request.title} {request.summary}"
    stocks = _infer_related_stocks(text)
    industries = _infer_related_industries(text)
    attention = _infer_attention_level(text, request.summary)
    sentiment = _infer_sentiment(text)
    sentiment_text = {"positive": "偏利好", "negative": "偏利空", "neutral": "中性观察"}.get(sentiment, "中性观察")
    if not stocks:
        stocks = [NewsBoardRelatedStock(code="000300.SH", name="沪深300", sentiment="neutral", reason="未识别到明确 A 股产业链，先作为市场风险偏好观察")]
    industry_text = "；".join(f"{name}：{chain}" for name, chain in industries) if industries else "未识别到明确行业，建议作为宏观/情绪消息观察"
    return NewsBoardAnalyzeResponse(
        summary=(
            f"关注度：{attention}。A股影响方向：{sentiment_text}。"
            f"涉及行业/板块：{industry_text}。"
            f"已列出 {len(stocks)} 个与该消息上下游更紧密的 A 股标的；需要结合板块成交额、涨停扩散和原始来源二次确认。"
        ),
        stocks=stocks,
    )


def _news_board_queries() -> list[str]:
    return [
        "24小时 中国 政策 A股 科技 产业链",
        "24小时 A股 异动 涨停 跌停 题材",
        "24小时 极端天气 股市 影响",
        "特朗普 马斯克 黄仁勋 最新 发言 股票",
        "美股 七巨头 财报 股价 最新",
        "英伟达 特斯拉 微软 苹果 Meta Amazon Alphabet 财报",
    ]


def _fetch_tushare_news_board_items(*, start_dt: datetime, end_dt: datetime, limit: int) -> list[dict[str, Any]]:
    del limit
    service = TushareService()
    if not service.token:
        return []

    china_tz = ZoneInfo("Asia/Shanghai")
    start_text = start_dt.astimezone(china_tz).strftime("%Y-%m-%d %H:%M:%S")
    end_text = end_dt.astimezone(china_tz).strftime("%Y-%m-%d %H:%M:%S")
    per_source_limit = 1500
    items: list[dict[str, Any]] = []
    for src, source_name in TUSHARE_NEWS_SOURCES:
        try:
            df = service.pro.news(src=src, start_date=start_text, end_date=end_text)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        for _, row in df.head(per_source_limit).iterrows():
            content = str(row.get("content") or "").strip()
            title = str(row.get("title") or "").strip()
            if not title:
                title = _title_from_content(content)
            if not title:
                continue
            items.append({
                "datetime": row.get("datetime"),
                "event_time": row.get("datetime"),
                "title": title,
                "content": content,
                "src": source_name,
                "source_type": src,
                "source_key": src,
                "source_level": "data_vendor",
            })
    return items


def _title_from_content(content: str) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    if not text:
        return ""
    sentence = re.split(r"[。！？!?]\s*", text, maxsplit=1)[0].strip()
    return (sentence or text)[:80]


def _fetch_free_primary_sources(*, start_dt: datetime, end_dt: datetime, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(_fetch_sec_filings(start_dt=start_dt, limit=limit))
    items.extend(_fetch_federal_register(start_dt=start_dt, end_dt=end_dt, limit=limit))
    items.extend(_fetch_nws_alerts(limit=limit))
    items.extend(_fetch_china_official_pages(limit=limit))
    return items


def _fetch_free_discovery_sources(*, start_dt: datetime, end_dt: datetime, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(_fetch_google_news_rss(limit=limit))
    items.extend(_fetch_gdelt_articles(start_dt=start_dt, end_dt=end_dt, limit=limit))
    return items


def _fetch_sec_filings(*, start_dt: datetime, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for company, cik in SEC_COMPANIES.items():
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        try:
            response = requests.get(url, headers=HTTP_HEADERS, timeout=4)
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue
        recent = data.get("filings", {}).get("recent", {}) if isinstance(data, dict) else {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accession_numbers = recent.get("accessionNumber") or []
        primary_docs = recent.get("primaryDocument") or []
        for index, form in enumerate(forms[:40]):
            filing_date = _parse_datetime(_safe_list_get(dates, index))
            if filing_date is None or filing_date < start_dt:
                continue
            accession = str(_safe_list_get(accession_numbers, index) or "").replace("-", "")
            primary_doc = str(_safe_list_get(primary_docs, index) or "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{primary_doc}" if accession and primary_doc else url
            form_text = str(form or "").strip()
            items.append({
                "datetime": filing_date.isoformat(),
                "event_time": filing_date.isoformat(),
                "title": f"{company} filed {form_text} with SEC",
                "content": f"{company} 最新 SEC 文件：{form_text}。CIK {cik}。",
                "src": "SEC EDGAR",
                "source_type": "sec_edgar",
                "source_level": "regulatory",
                "url": filing_url,
            })
            if len(items) >= limit:
                return items
    return items


def _fetch_federal_register(*, start_dt: datetime, end_dt: datetime, limit: int) -> list[dict[str, Any]]:
    terms = ("artificial intelligence", "semiconductor", "tariff")
    items: list[dict[str, Any]] = []
    for term in terms:
        url = (
            "https://www.federalregister.gov/api/v1/documents.json"
            f"?conditions%5Bterm%5D={quote_plus(term)}"
            f"&conditions%5Bpublication_date%5D%5Bgte%5D={start_dt.date().isoformat()}"
            f"&conditions%5Bpublication_date%5D%5Blte%5D={end_dt.date().isoformat()}"
            "&order=newest&per_page=10"
        )
        try:
            response = requests.get(url, headers=HTTP_HEADERS, timeout=4)
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue
        for doc in data.get("results", []) if isinstance(data, dict) else []:
            title = str(doc.get("title") or "").strip()
            if not title:
                continue
            published = _parse_datetime(doc.get("publication_date"))
            if published is not None and published < start_dt:
                continue
            items.append({
                "datetime": (published or utc_now()).isoformat(),
                "event_time": (published or utc_now()).isoformat(),
                "title": title,
                "content": str(doc.get("abstract") or doc.get("type") or "")[:400],
                "src": "Federal Register",
                "source_type": "federal_register",
                "source_level": "regulatory",
                "url": doc.get("html_url") or doc.get("pdf_url"),
            })
            if len(items) >= limit:
                return items
    return items


def _fetch_nws_alerts(*, limit: int) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            "https://api.weather.gov/alerts/active?status=actual&message_type=alert",
            headers=HTTP_HEADERS,
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for feature in data.get("features", []) if isinstance(data, dict) else []:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict):
            continue
        title = str(props.get("headline") or props.get("event") or "").strip()
        if not title:
            continue
        published = _parse_datetime(props.get("sent") or props.get("effective") or props.get("onset"))
        items.append({
            "datetime": (published or utc_now()).isoformat(),
            "event_time": (published or utc_now()).isoformat(),
            "title": title,
            "content": str(props.get("description") or props.get("instruction") or "")[:500],
            "src": "National Weather Service",
            "source_type": "nws_alerts",
            "source_level": "official",
            "url": props.get("@id") or props.get("uri"),
        })
        if len(items) >= limit:
            break
    return items


def _fetch_china_official_pages(*, limit: int) -> list[dict[str, Any]]:
    sources = (
        ("中国政府网", "https://www.gov.cn/zhengce/"),
        ("证监会", "https://www.csrc.gov.cn/csrc/c100028/zfxxgk_zdgk.shtml"),
        ("工信部", "https://www.miit.gov.cn/xwdt/gxdt/"),
    )
    items: list[dict[str, Any]] = []
    for source_name, url in sources:
        try:
            response = requests.get(url, headers={**HTTP_HEADERS, "User-Agent": "Mozilla/5.0"}, timeout=4)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
        except Exception:
            continue
        for href, raw_title in re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", response.text, re.I | re.S):
            title = _clean_html(raw_title)
            if not _is_relevant_official_title(title):
                continue
            absolute_url = _absolute_url(url, href)
            published = _parse_datetime_from_url(absolute_url)
            items.append({
                "datetime": (published or utc_now()).isoformat(),
                "event_time": (published or utc_now()).isoformat(),
                "title": title,
                "content": "",
                "src": source_name,
                "source_type": "china_official",
                "source_level": "official",
                "url": absolute_url,
            })
            if len(items) >= limit:
                return items
    return items


def _fetch_google_news_rss(*, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for query in GOOGLE_NEWS_QUERIES[:4]:
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            response = requests.get(url, headers={**HTTP_HEADERS, "User-Agent": "Mozilla/5.0"}, timeout=5)
            response.raise_for_status()
            root = ET.fromstring(response.text)
        except Exception:
            continue
        for node in root.findall(".//item"):
            title = _strip_google_news_source(node.findtext("title") or "")
            published = _parse_datetime(node.findtext("pubDate"))
            items.append({
                "datetime": (published or utc_now()).isoformat(),
                "event_time": (published or utc_now()).isoformat(),
                "title": title,
                "content": "",
                "src": node.findtext("source") or "Google News",
                "source_type": "google_news",
                "source_level": "media",
                "url": node.findtext("link"),
                "query": query,
            })
            if len(items) >= limit:
                return items
    return items


def _fetch_gdelt_articles(*, start_dt: datetime, end_dt: datetime, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for query in GDELT_QUERIES[:1]:
        url = (
            "https://api.gdeltproject.org/api/v2/doc/doc?"
            f"query={quote_plus(query)}&mode=ArtList&format=json&sort=DateDesc"
            f"&startdatetime={start_dt.strftime('%Y%m%d%H%M%S')}"
            f"&enddatetime={end_dt.strftime('%Y%m%d%H%M%S')}"
            f"&maxrecords={min(limit, 30)}"
        )
        try:
            response = requests.get(url, headers=HTTP_HEADERS, timeout=5)
            if response.status_code == 429 or "Please limit requests" in response.text[:120]:
                continue
            response.raise_for_status()
            data = response.json()
        except Exception:
            continue
        for article in data.get("articles", []) if isinstance(data, dict) else []:
            title = str(article.get("title") or "").strip()
            if not title:
                continue
            published = _parse_datetime(article.get("seendate"))
            items.append({
                "datetime": (published or utc_now()).isoformat(),
                "event_time": (published or utc_now()).isoformat(),
                "title": title,
                "content": "",
                "src": article.get("domain") or "GDELT",
                "source_type": "gdelt",
                "source_level": "media",
                "url": article.get("url"),
                "query": query,
            })
            if len(items) >= limit:
                return items
    return items


def _normalize_news_items(
    raw_items: list[dict[str, Any]],
    *,
    start_dt: datetime,
    now: datetime,
    limit: int,
) -> tuple[list[NewsBoardItem], int]:
    del limit
    seen: set[str] = set()
    result: list[NewsBoardItem] = []
    duplicate_count = 0
    for raw in raw_items:
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        source_type = str(raw.get("source_type") or raw.get("source_key") or "")
        if source_type == "public_web" and not _is_public_news_article(raw):
            continue
        dedupe_key = re.sub(r"\s+", "", title).lower()
        if dedupe_key in seen:
            duplicate_count += 1
            continue
        seen.add(dedupe_key)

        if source_type in {src for src, _ in TUSHARE_NEWS_SOURCES}:
            published_at = _parse_china_datetime(raw.get("datetime") or raw.get("published_at") or raw.get("pub_time") or raw.get("date"))
            event_time = _parse_china_datetime(raw.get("event_time")) or published_at
        else:
            published_at = _parse_datetime(raw.get("datetime") or raw.get("published_at") or raw.get("pub_time") or raw.get("date"))
            event_time = _parse_datetime(raw.get("event_time")) or published_at
        if published_at is None and source_type == "public_web":
            published_at = _parse_datetime_from_url(str(raw.get("url") or ""))
            event_time = published_at
        if published_at is not None and published_at < start_dt:
            continue
        if published_at is None and source_type == "public_web":
            continue
        elif published_at is None:
            published_at = now

        summary = str(raw.get("content") or raw.get("summary") or "").strip()
        source = str(raw.get("src") or raw.get("source") or raw.get("source_key") or "news").strip()
        text = f"{title} {summary}"
        category = source_type or str(raw.get("category") or _infer_category(text))
        related_stocks = _infer_related_stocks(text)
        item = NewsBoardItem(
            id=_stable_id(title=title, source=source, published_at=published_at),
            title=title,
            summary=summary[:260],
            category=category,
            source=source,
            event_time=event_time,
            eventTime=event_time,
            published_at=published_at,
            publishedAt=published_at,
            ingested_at=now,
            ingestedAt=now,
            impact=_infer_impact(text, category),
            region=_infer_region(text, source),
            url=raw.get("url"),
            source_url=raw.get("url"),
            sourceUrl=raw.get("url"),
            source_level=str(raw.get("source_level") or _infer_source_level(source_type)),
            sourceLevel=str(raw.get("source_level") or _infer_source_level(source_type)),
            source_type=source_type or None,
            related_stocks=related_stocks,
            relatedStocks=related_stocks,
        )
        result.append(item)
    result.sort(key=lambda item: (_source_priority(item.source_type), item.published_at or now), reverse=True)
    return result, duplicate_count


def _balanced_limit(items: list[NewsBoardItem], *, limit: int) -> list[NewsBoardItem]:
    selected: list[NewsBoardItem] = []
    seen_ids: set[str] = set()
    category_quota = max(4, min(20, limit // 5))
    for category in ("us_market", "weather", "people", "policy", "price"):
        count = 0
        for item in items:
            if item.id in seen_ids or item.category != category:
                continue
            selected.append(item)
            seen_ids.add(item.id)
            count += 1
            if len(selected) >= limit:
                return selected
            if count >= category_quota:
                break

    per_source_cap = max(3, min(6, limit // 5 or 4))
    counts: dict[str, int] = {}
    for item in items:
        if item.id in seen_ids:
            continue
        key = item.source_type or item.source
        if counts.get(key, 0) >= per_source_cap:
            continue
        selected.append(item)
        seen_ids.add(item.id)
        counts[key] = counts.get(key, 0) + 1
        if len(selected) >= limit:
            return selected
    if len(selected) < limit:
        for item in items:
            if item.id in seen_ids:
                continue
            selected.append(item)
            seen_ids.add(item.id)
            if len(selected) >= limit:
                break
    return selected


def _event_relevance(item: NewsBoardItem) -> int:
    text = f"{item.title} {item.summary}".lower()
    score = 0
    for keyword in ("jensen", "huang", "黄仁勋", "elon", "musk", "马斯克", "nvidia", "marvell", "tesla", "ai", "semiconductor", "tariff", "trump", "pharma", "biotech", "fda", "china", "policy"):
        if keyword in text:
            score += 1
    if item.relatedStocks:
        score += 2
    if item.impact == "high":
        score += 2
    return score


def _fetch_extra_tushare_news(*, start_date: date, end_date: date, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    service = TushareService()
    for src in ("", "yicai", "sina", "wallstreetcn"):
        fetched = service.get_news_items(
            src=src,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            limit=max(10, limit // 2),
        )
        for item in fetched:
            item["source_type"] = "tushare"
            item["source_key"] = item.get("src") or src or "tushare"
        items.extend(fetched)
    return items


def _is_public_news_article(raw: dict[str, Any]) -> bool:
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("url") or "")
    if not title or len(title) < 8:
        return False
    bad_titles = ("频道", "环球市场", "财经大V", "黄豆油", "投资者大会")
    if any(fragment in title for fragment in bad_titles) or title.endswith(">>"):
        return False
    article_markers = ("/doc-", "/roll/", "/stock/", "/money/", "/fund/", "/china/", "/world/")
    return any(marker in url for marker in article_markers)


def _source_priority(source_type: str | None) -> int:
    source_order = {src: len(TUSHARE_NEWS_SOURCES) - index for index, (src, _) in enumerate(TUSHARE_NEWS_SOURCES)}
    if source_type in source_order:
        return source_order[source_type]
    if source_type in {"sec_edgar", "federal_register", "nws_alerts", "china_official"}:
        return 3
    if source_type in {"google_news", "gdelt", "search"}:
        return 2
    if source_type == "public_web":
        return 2
    return 1


def _infer_source_level(source_type: str | None) -> str:
    if source_type in {src for src, _ in TUSHARE_NEWS_SOURCES}:
        return "data_vendor"
    if source_type == "sec_edgar":
        return "regulatory"
    if source_type in {"federal_register", "nws_alerts", "china_official"}:
        return "official"
    if source_type == "tushare":
        return "data_vendor"
    return "media"


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            pass
        formats = (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y%m%d %H:%M:%S",
            "%Y%m%d%H%M%S",
            "%Y%m%d",
        )
        parsed = None
        for fmt in formats:
            try:
                parsed = datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_china_datetime(value: Any) -> datetime | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    text = str(value or "").strip()
    if isinstance(value, datetime) and value.tzinfo is not None:
        return parsed
    if re.search(r"(Z|[+-]\d{2}:?\d{2})$", text):
        return parsed
    china_tz = ZoneInfo("Asia/Shanghai")
    naive = parsed.replace(tzinfo=None)
    return naive.replace(tzinfo=china_tz).astimezone(timezone.utc)


def _parse_datetime_from_url(url: str) -> datetime | None:
    match = re.search(r"/(20\d{2})-(\d{2})-(\d{2})/", url)
    if not match:
        return None
    try:
        return datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def _safe_list_get(values: Any, index: int) -> Any:
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return None


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _absolute_url(base_url: str, href: str) -> str:
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        match = re.match(r"^(https?://[^/]+)", base_url)
        return f"{match.group(1) if match else ''}{href}"
    return base_url.rsplit("/", 1)[0] + "/" + href


def _is_relevant_official_title(title: str) -> bool:
    if len(title) < 8 or len(title) > 140:
        return False
    bad = ("首页", "登录", "注册", "邮箱", "微博", "微信", "客户端", "专题")
    return not any(fragment in title for fragment in bad)


def _strip_google_news_source(title: str) -> str:
    return re.sub(r"\s+-\s+[^-]{2,80}$", "", title or "").strip()


def _infer_category(text: str) -> str:
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword.lower() in text.lower() for keyword in keywords):
            return category
    return "us_market" if re.search(r"\b(NVDA|TSLA|AAPL|MSFT|META|AMZN|GOOGL)\b", text, re.I) else "price"


def _is_weather_news(title: str, summary: str) -> bool:
    strong_keywords = ("暴雨", "台风", "高温", "寒潮", "洪水", "地震", "极端天气", "灾害", "气象", "飓风", "干旱", "强对流", "大雾", "厄尔尼诺", "拉尼娜")
    title_text = title or ""
    if any(keyword in title_text for keyword in strong_keywords):
        return True
    text = f"{title} {summary}"
    return any(keyword in text for keyword in ("世界气象组织", "中央气象台", "中国气象局", "防汛", "强降雨"))


def _infer_impact(text: str, category: str) -> str:
    high_keywords = ("政策", "监管", "关税", "暴雨", "台风", "大涨", "大跌", "涨停", "跌停", "黄仁勋", "特朗普")
    if category == "policy" or any(keyword in text for keyword in high_keywords):
        return "high"
    if category in {"people", "weather", "us_market"}:
        return "medium"
    return "low"


def _infer_region(text: str, source: str) -> str:
    if any(keyword in text for keyword in ("美股", "纳指", "道指", "标普", "特朗普", "马斯克", "黄仁勋", "NVIDIA", "Tesla")):
        return "美国"
    if any(keyword in text for keyword in ("中国", "A股", "国务院", "证监会", "工信部", "发改委")):
        return "中国"
    if source in {name for _, name in TUSHARE_NEWS_SOURCES}:
        return "中国"
    return "全球"


def _infer_related_stocks(text: str) -> list[NewsBoardRelatedStock]:
    lower_text = text.lower()
    stocks: list[NewsBoardRelatedStock] = []
    seen: set[str] = set()
    sentiment = _infer_sentiment(text)
    for keywords, stock in STOCK_HINTS:
        if not any(keyword.lower() in lower_text for keyword in keywords):
            continue
        code, name, reason = stock
        if code in seen:
            continue
        seen.add(code)
        stocks.append(NewsBoardRelatedStock(code=code, name=name, sentiment=sentiment, reason=reason))
        if len(stocks) >= 8:
            break
    return stocks


def _infer_related_industries(text: str) -> list[tuple[str, str]]:
    lower_text = text.lower()
    industries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for keywords, industry in INDUSTRY_HINTS:
        if not any(keyword.lower() in lower_text for keyword in keywords):
            continue
        name, chain = industry
        if name in seen:
            continue
        seen.add(name)
        industries.append((name, chain))
        if len(industries) >= 5:
            break
    return industries


def _infer_attention_level(title: str, summary: str) -> str:
    text = f"{title} {summary}"
    high_keywords = ("黄仁勋", "马斯克", "特朗普", "英伟达", "涨停", "跌停", "大涨", "大跌", "监管", "政策", "关税", "突发", "财联社", "金十数据")
    medium_keywords = ("AI", "芯片", "半导体", "机器人", "美股", "创新药", "暴雨", "台风", "厄尔尼诺")
    hit_count = sum(1 for keyword in high_keywords if keyword in text)
    if hit_count >= 2 or len(summary) >= 180:
        return "高，具备跨市场或板块扩散条件"
    if hit_count == 1 or any(keyword.lower() in text.lower() for keyword in medium_keywords):
        return "中，需要观察同题材多源扩散"
    return "低，暂按单条快讯观察"


def _infer_sentiment(text: str) -> str:
    if any(keyword in text for keyword in NEGATIVE_KEYWORDS):
        return "negative"
    if any(keyword in text for keyword in POSITIVE_KEYWORDS):
        return "positive"
    return "neutral"


def _stable_id(*, title: str, source: str, published_at: datetime) -> str:
    raw = f"{title}|{source}|{published_at.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _build_source_status(raw_items: list[dict[str, Any]], items: list[NewsBoardItem]) -> list[NewsBoardSourceStatus]:
    raw_counts: dict[str, int] = {}
    for raw in raw_items:
        key = str(raw.get("source_type") or raw.get("source_key") or raw.get("src") or raw.get("source") or "news")
        raw_counts[key] = raw_counts.get(key, 0) + 1
    visible_counts: dict[str, int] = {}
    for item in items:
        key = item.source_type or item.source
        visible_counts[key] = visible_counts.get(key, 0) + 1
    statuses = [
        NewsBoardSourceStatus(
            name=name,
            source_key=src,
            available=raw_counts.get(src, 0) > 0,
            item_count=raw_counts.get(src, 0),
            description=f"Tushare pro.news(src='{src}')",
        )
        for src, name in TUSHARE_NEWS_SOURCES
    ]
    statuses.append(NewsBoardSourceStatus(
        name="24H 可展示",
        source_key="visible",
        available=bool(items),
        item_count=sum(visible_counts.values()),
        description="去重和分门别类过滤后的消息",
    ))
    return statuses
