"""News board cache service layer.

Handles Tushare news fetching, normalisation, deduplication (fingerprint &
similarity), and Redis-backed storage/retrieval.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time as _time_module
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from app.cache import cache
from app.config import settings
from app.schemas import (
    NewsBoardItem,
    NewsBoardItemsResponse,
    NewsBoardRelatedStock,
    NewsBoardSourceStatus,
)
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

CHINA_TZ = ZoneInfo("Asia/Shanghai")

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
TUSHARE_SOURCE_LABELS = dict(TUSHARE_NEWS_SOURCES)

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
    (("白银", "银价", "现货白银", "贵金属", "金银"), ("000603.SZ", "盛达资源", "白银采选与铅锌精矿")),
    (("白银", "银价", "现货白银", "贵金属", "金银"), ("601899.SH", "紫金矿业", "金铜银综合矿企")),
    (("黄金", "金价", "现货黄金", "贵金属", "金银"), ("600547.SH", "山东黄金", "黄金采选冶炼")),
    (("黄金", "金价", "现货黄金", "贵金属", "金银"), ("000975.SZ", "山金国际", "金银贵金属采选")),
    (("贵金属", "金银", "避险", "通胀"), ("600547.SH", "山东黄金", "贵金属避险资产")),
    (("贵金属", "金银", "避险", "通胀"), ("601899.SH", "紫金矿业", "多金属矿企龙头")),
    (("铜价", "铜", "现货铜", "基本金属"), ("603799.SH", "华友钴业", "铜钴矿采选")),
    (("铜价", "铜", "现货铜", "基本金属"), ("601899.SH", "紫金矿业", "铜金矿采选冶炼")),
    (("油价", "原油", "石油", "能源"), ("601857.SH", "中国石油", "油气勘探开采")),
    (("油价", "原油", "石油", "能源"), ("600028.SH", "中国石化", "石化与炼化")),
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
    (("白银", "银价", "现货白银", "黄金", "金价", "贵金属", "金银"), ("贵金属", "白银采选、黄金采选、铅锌伴生银、避险资产")),
    (("铜价", "铜", "现货铜", "基本金属"), ("基本金属", "铜矿采选、冶炼、加工")),
    (("原油", "油价", "石油"), ("石油能源", "油气勘探、开采、炼化")),
]

NEGATIVE_KEYWORDS = ("利空", "下调", "处罚", "监管", "调查", "大跌", "跳水", "跌超", "下跌", "走低", "灾害", "理赔")
POSITIVE_KEYWORDS = ("利好", "上调", "突破", "扩张", "增长", "订单", "政策支持", "大涨", "拉升", "涨超", "上涨", "新高")

KEY_INDEX_ZSET = "news:items"
KEY_FINGERPRINT_ZSET = "news:fingerprints"
KEY_ITEM_PREFIX = "news:item:"
KEY_FINGERPRINT_PREFIX = "news:fingerprint:"
FINGERPRINT_KEY_SIM = "news:near:"
KEY_SYNC_PREFIX = "news:sync:"
LOCK_KEY = "news:update_lock"
STATUS_KEY = "news:status"
ENTITY_BUCKET_SECONDS = 1800
NEAR_BUCKET_SECONDS = 900
TITLE_SIMILARITY_THRESHOLD = 0.86
ENTITY_TITLE_SIMILARITY_THRESHOLD = 0.72
ENTITY_OVERLAP_THRESHOLD = 0.70


class NewsBoardCacheService:
    """Service that manages news-board caching lifecycle."""

    def __init__(self) -> None:
        self._cache = cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_items(
        self,
        *,
        window_hours: int | None = None,
        limit: int | None = None,
        before_ts: float | None = None,
    ) -> NewsBoardItemsResponse:
        """Read news items from Redis within the given time window.

        If before_ts is given, return items older than that timestamp
        (cursor-based pagination for infinite scroll).
        """
        if window_hours is None:
            window_hours = settings.news_board_window_hours
        if limit is None:
            limit = 50

        now = utc_now()
        min_ts = (now - timedelta(hours=window_hours)).timestamp()
        max_ts = before_ts if before_ts else now.timestamp()

        raw = self._cache
        if not raw.is_redis_available:
            return NewsBoardItemsResponse(
                window_hours=window_hours,
                generated_at=now,
                items=[],
                sources=[],
                duplicate_count=0,
                message="Redis 不可用，新闻缓存服务暂时无法提供服务。",
            )

        items: list[NewsBoardItem] = []
        stale_ids: list[str] = []
        offset = 0
        batch_size = max(limit * 2, 50)
        exhausted = False

        while len(items) <= limit:
            members = raw.zrevrangebyscore(KEY_INDEX_ZSET, max_ts, min_ts, start=offset, num=batch_size)
            if not members:
                exhausted = True
                break
            offset += len(members)
            if len(members) < batch_size:
                exhausted = True

            item_ids = [_redis_member_text(member[0]) for member in members]
            full_keys = [f"{KEY_ITEM_PREFIX}{ik}" for ik in item_ids]
            raw_items = raw.mget(full_keys)

            for item_id in item_ids:
                data = raw_items.get(f"{KEY_ITEM_PREFIX}{item_id}")
                if data is None:
                    stale_ids.append(item_id)
                    continue
                try:
                    item = NewsBoardItem(**data)
                    item.source = _source_label(item.source or item.source_type)
                    items.append(item)
                    if len(items) > limit:
                        break
                except Exception:
                    logger.warning("解析缓存新闻条目失败: %s", item_id)
                    stale_ids.append(item_id)
            if exhausted:
                break

        if stale_ids:
            raw.zrem(KEY_INDEX_ZSET, *stale_ids)

        has_more = len(items) > limit

        return NewsBoardItemsResponse(
            window_hours=window_hours,
            generated_at=now,
            items=items[:limit],
            sources=[],
            duplicate_count=0,
            has_more=has_more,
            message=None,
        )

    def update_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Perform one full update cycle: fetch from Tushare, normalize, dedup, write."""
        if now is None:
            now = utc_now()

        if not self._cache.is_redis_available:
            return {"status": "unavailable", "fetched": 0, "inserted": 0, "duplicate": 0, "errors": ["Redis 不可用"]}

        if not self._cache.acquire_lock(LOCK_KEY, ttl_seconds=settings.news_board_lock_ttl_seconds):
            return {"status": "skipped", "reason": "已有其他 worker 正在更新"}

        try:
            result = self._do_update(now=now)
            self._store_status(result, now=now)
            return result
        finally:
            self._cache.release_lock(LOCK_KEY)

    def cleanup_expired_indexes(self, *, now: datetime | None = None) -> int:
        """Remove ZSET members older than 24 h from the index ZSETs."""
        if now is None:
            now = utc_now()
        cutoff_ts = (now - timedelta(hours=settings.news_board_window_hours)).timestamp()
        raw = self._cache
        total = 0
        total += raw.zremrangebyscore(KEY_INDEX_ZSET, 0, cutoff_ts)
        total += raw.zremrangebyscore(KEY_FINGERPRINT_ZSET, 0, cutoff_ts)
        return total

    def get_status(self) -> dict[str, Any]:
        """Return current cached status."""
        data = self._cache.get(STATUS_KEY)
        if data is None:
            return {
                "redis_available": self._cache.is_redis_available,
                "last_update": None,
                "total_fetched": 0,
                "total_inserted": 0,
                "total_duplicate": 0,
                "source_watermarks": {},
                "error_sources": [],
                "index_count": 0,
            }
        data["redis_available"] = self._cache.is_redis_available
        data["index_count"] = self._cache.zcard(KEY_INDEX_ZSET)
        return data

    def search_items(
        self,
        *,
        keyword: str,
        window_hours: int | None = None,
        limit: int = 100,
    ) -> NewsBoardItemsResponse:
        """Search news items by keyword in title and summary."""
        if window_hours is None:
            window_hours = settings.news_board_window_hours
        now = utc_now()
        min_ts = (now - timedelta(hours=window_hours)).timestamp()
        max_ts = now.timestamp()

        raw = self._cache
        if not raw.is_redis_available:
            return NewsBoardItemsResponse(
                window_hours=window_hours,
                generated_at=now,
                items=[],
                sources=[],
                duplicate_count=0,
                message="Redis 不可用",
            )

        members = raw.zrevrangebyscore(KEY_INDEX_ZSET, max_ts, min_ts, start=0, num=1000)
        if not members:
            return NewsBoardItemsResponse(
                window_hours=window_hours,
                generated_at=now,
                items=[],
                sources=[],
                duplicate_count=0,
                message=None,
            )

        item_ids = [_redis_member_text(member[0]) for member in members]
        full_keys = [f"{KEY_ITEM_PREFIX}{ik}" for ik in item_ids]
        raw_items = raw.mget(full_keys)

        kw = keyword.lower()
        items: list[NewsBoardItem] = []
        for ik in item_ids:
            data = raw_items.get(f"{KEY_ITEM_PREFIX}{ik}")
            if data is None:
                continue
            try:
                item = NewsBoardItem(**data)
                item.source = _source_label(item.source or item.source_type)
            except Exception:
                continue
            haystack = f"{item.title} {item.summary}".lower()
            if kw in haystack:
                items.append(item)
                if len(items) >= limit:
                    break

        return NewsBoardItemsResponse(
            window_hours=window_hours,
            generated_at=now,
            items=items,
            sources=[],
            duplicate_count=0,
            has_more=len(items) >= limit,
            message=f'搜索 "{keyword}" 找到 {len(items)} 条结果' if items else f'未找到包含 "{keyword}" 的消息',
        )

    # ------------------------------------------------------------------
    # Normalisation helpers (migrated from API)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_news_items(
        raw_items: list[dict[str, Any]],
        *,
        start_dt: datetime,
        now: datetime,
    ) -> tuple[list[NewsBoardItem], int]:
        seen: set[str] = set()
        result: list[NewsBoardItem] = []
        duplicate_count = 0
        for raw in raw_items:
            title = str(raw.get("title") or "").strip()
            if not title:
                continue
            source_type = str(raw.get("source_type") or raw.get("source_key") or "")
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

            if published_at is not None and published_at < start_dt:
                continue
            if published_at is None:
                published_at = now

            summary = str(raw.get("content") or raw.get("summary") or "").strip()
            source = _source_label(str(raw.get("src") or raw.get("source") or raw.get("source_key") or "news").strip())
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
                source_level=str(raw.get("source_level") or "data_vendor"),
                sourceLevel=str(raw.get("source_level") or "data_vendor"),
                source_type=source_type or None,
                related_stocks=related_stocks,
                relatedStocks=related_stocks,
            )
            result.append(item)
        result.sort(
            key=lambda item: ((item.event_time or item.published_at or now).timestamp()),
            reverse=True,
        )
        return result, duplicate_count

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------

    @staticmethod
    def fetch_tushare_source(
        src: str,
        source_name: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch news from a single Tushare source for the given time window."""
        from app.services.tushare_service import TushareService

        service = TushareService()
        if not service.token:
            return [], f"{source_name}: Tushare token 未配置"

        start_text = start_dt.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        end_text = end_dt.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")
        per_source_limit = settings.news_board_fetch_limit_per_source

        try:
            df = service.pro.news(src=src, start_date=start_text, end_date=end_text)
        except Exception as exc:
            return [], f"{source_name}: {exc}"

        if df is None or df.empty:
            return [], None

        items: list[dict[str, Any]] = []
        fetched = 0
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
            fetched += 1

        if fetched >= per_source_limit:
            logger.warning(
                "%s 单次拉取达到上限 %d，可能存在数据截断",
                source_name,
                per_source_limit,
            )
        return items, None

    # ------------------------------------------------------------------
    # Watermark helpers
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_fetch_window(src: str, now: datetime) -> tuple[datetime, datetime]:
        """Determine the fetch time window for a source."""
        cache_key = f"{KEY_SYNC_PREFIX}{src}"
        raw_data = cache.get(cache_key)
        window_hours = settings.news_board_window_hours
        overlap = timedelta(minutes=settings.news_board_overlap_minutes)

        if raw_data is None:
            start = now - timedelta(hours=window_hours)
        else:
            try:
                last_end = datetime.fromisoformat(raw_data)
            except (TypeError, ValueError):
                start = now - timedelta(hours=window_hours)
            else:
                start = last_end - overlap
                floor = now - timedelta(hours=window_hours)
                if start < floor:
                    start = floor

        end = now
        return start, end

    @staticmethod
    def update_sync_watermark(src: str, end: datetime) -> None:
        """Update the sync watermark for a source after successful fetch."""
        cache_key = f"{KEY_SYNC_PREFIX}{src}"
        cache.set(cache_key, end.isoformat(), ttl=3600 * 48)

    @staticmethod
    def _strip_title_markers(title: str) -> str:
        """Normalize a title by removing common source prefixes and brackets.

        Strategy:
        1. If title has `【...】` brackets, extract content inside as headline
        2. Strip other prefixes (source names, date prefixes, malformed brackets)
        3. Collapse whitespace and lowercase
        """
        t = title.strip()

        headline_match = re.match(r"【(.+?)】", t)
        if headline_match and len(headline_match.group(1)) >= 6:
            t = headline_match.group(1).strip()
        else:
            t = re.sub(r"^【[^】]*】", "", t)

        t = re.sub(r"^\[[^\]]*\]\s*", "", t)
        t = re.sub(r"^\S{2,6}讯[：:]", "", t)
        t = re.sub(r"^\S{2,6}\d{1,2}月\d{1,2}日电[，,]\s*", "", t)
        t = re.sub(r"^\[[Pp][a-z]{0,10}\s*", "", t)
        t = re.sub(r"^\[[A-Za-z]{0,10}\s*", "", t)
        t = re.sub(r"\s+", "", t)
        return t.lower()

    # ------------------------------------------------------------------
    # Dedup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_news_text(title: str, summary: str) -> str:
        """Normalize title+summary for comparison."""
        text = f"{title} {summary}".lower()
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def extract_news_entities(title: str, summary: str) -> dict[str, list[str]]:
        """Extract entities from news text using keyword matching."""
        text = f"{title} {summary}"
        companies: list[str] = []
        keywords_set: set[str] = set()
        company_patterns = [
            "英伟达", "NVIDIA", "特斯拉", "Tesla", "苹果", "Apple", "微软", "Microsoft",
            "亚马逊", "Amazon", "Meta", "Alphabet", "谷歌", "Google", "Marvell", "迈威尔",
            "中芯国际", "华为", "字节跳动", "腾讯", "阿里", "百度", "京东",
        ]
        for pat in company_patterns:
            if pat.lower() in text.lower():
                companies.append(pat)

        action_patterns = ["涨", "跌", "收购", "发布", "裁员", "融资", "上市", "处罚", "监管"]
        for pat in action_patterns:
            if pat in text:
                keywords_set.add(pat)

        return {"companies": companies, "keywords": list(keywords_set)}

    @staticmethod
    def build_news_fingerprints(item: NewsBoardItem) -> dict[str, str]:
        """Build fingerprints for a news item."""
        normalized = NewsBoardCacheService.normalize_news_text(item.title, item.summary)
        entities = NewsBoardCacheService.extract_news_entities(item.title, item.summary)

        hash_full = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:24]

        title_raw = NewsBoardCacheService._strip_title_markers(item.title)
        hash_title = hashlib.sha1(title_raw.encode("utf-8")).hexdigest()[:24] if len(title_raw) >= 8 else ""

        entity_key = "|".join(
            sorted(set(entities.get("companies", [])) | set(entities.get("keywords", [])))
        )
        hash_entities = hashlib.sha1(entity_key.encode("utf-8")).hexdigest()[:24] if entity_key else ""

        return {
            "full": hash_full,
            "title": hash_title,
            "entity": hash_entities,
        }

    @staticmethod
    def is_duplicate(item: NewsBoardItem) -> tuple[bool, str | None]:
        """Check if a news item is a duplicate of an existing one.

        Returns (is_duplicate, fingerprint_key) tuple.
        """
        fps = NewsBoardCacheService.build_news_fingerprints(item)
        event_ts = (item.event_time or item.published_at or utc_now()).timestamp()
        raw = cache

        # Layer 0: pure title match (same title, different summary — e.g. sources copy same headline)
        if fps.get("title"):
            fp_key = f"{KEY_FINGERPRINT_PREFIX}title:{fps['title']}"
            existing = raw.get(fp_key)
            if existing is not None:
                return True, f"title:{fps['title']}"

        # Layer 1: full title+summary match
        if fps["full"]:
            fp_key = f"{KEY_FINGERPRINT_PREFIX}{fps['full']}"
            existing = raw.get(fp_key)
            if existing is not None:
                return True, fps["full"]

        # Check entity + time bucket match (30 min)
        if fps.get("entity"):
            entity_fp = fps["entity"]
            time_bucket = int(event_ts // ENTITY_BUCKET_SECONDS)
            combined_fp = f"{entity_fp}:{time_bucket}"
            fp_key = f"{KEY_FINGERPRINT_PREFIX}{combined_fp}"
            existing_id = raw.get(fp_key)
            existing_item = NewsBoardCacheService._get_cached_item(existing_id) if existing_id is not None else None
            if existing_item and NewsBoardCacheService._is_similar_event(item, existing_item):
                return True, combined_fp

        # Check cross-source near-duplicate via title similarity
        normalized = NewsBoardCacheService._strip_title_markers(item.title)
        if len(normalized) >= 12:
            near_fp = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:24]
            time_bucket = int(event_ts // NEAR_BUCKET_SECONDS)
            near_key = f"{FINGERPRINT_KEY_SIM}{near_fp}:{time_bucket}"
            existing_near = raw.get(near_key)
            existing_item = NewsBoardCacheService._get_cached_item(existing_near) if existing_near is not None else None
            if existing_item and existing_item.id != item.id and NewsBoardCacheService._title_similarity(item.title, existing_item.title) >= TITLE_SIMILARITY_THRESHOLD:
                return True, near_fp

        return False, None

    @staticmethod
    def _get_cached_item(item_id: Any) -> NewsBoardItem | None:
        if item_id is None:
            return None
        item_key = f"{KEY_ITEM_PREFIX}{_redis_member_text(item_id)}"
        data = cache.get(item_key)
        if data is None:
            return None
        try:
            return NewsBoardItem(**data)
        except Exception:
            return None

    @staticmethod
    def _title_similarity(left: str, right: str) -> float:
        left_norm = NewsBoardCacheService._strip_title_markers(left)
        right_norm = NewsBoardCacheService._strip_title_markers(right)
        if not left_norm or not right_norm:
            return 0.0
        return SequenceMatcher(None, left_norm, right_norm).ratio()

    @staticmethod
    def _entity_overlap(left: NewsBoardItem, right: NewsBoardItem) -> float:
        left_entities = NewsBoardCacheService.extract_news_entities(left.title, left.summary)
        right_entities = NewsBoardCacheService.extract_news_entities(right.title, right.summary)
        left_set = set(left_entities.get("companies", [])) | set(left_entities.get("keywords", []))
        right_set = set(right_entities.get("companies", [])) | set(right_entities.get("keywords", []))
        if not left_set or not right_set:
            return 0.0
        return len(left_set & right_set) / max(len(left_set), len(right_set))

    @staticmethod
    def _is_similar_event(left: NewsBoardItem, right: NewsBoardItem) -> bool:
        title_similarity = NewsBoardCacheService._title_similarity(left.title, right.title)
        if title_similarity >= TITLE_SIMILARITY_THRESHOLD:
            return True
        entity_overlap = NewsBoardCacheService._entity_overlap(left, right)
        return (
            entity_overlap >= ENTITY_OVERLAP_THRESHOLD
            and title_similarity >= ENTITY_TITLE_SIMILARITY_THRESHOLD
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_update(self, *, now: datetime) -> dict[str, Any]:
        total_fetched = 0
        total_inserted = 0
        total_duplicate = 0
        errors: list[str] = []

        for src, source_name in TUSHARE_NEWS_SOURCES:
            start, end = self.resolve_fetch_window(src, now)
            raw_items, error = self.fetch_tushare_source(src, source_name, start, end)

            if error:
                errors.append(error)
                continue

            start_dt_for_norm = now - timedelta(hours=settings.news_board_window_hours)
            normalized, dup_in_batch = self.normalize_news_items(raw_items, start_dt=start_dt_for_norm, now=now)
            total_fetched += len(raw_items)
            total_duplicate += dup_in_batch

            for item in normalized:
                is_dup, _ = self.is_duplicate(item)
                if is_dup:
                    total_duplicate += 1
                    continue
                self._write_item(item)
                total_inserted += 1

            self.update_sync_watermark(src, end)

        self.cleanup_expired_indexes(now=now)

        sources_updated = len(TUSHARE_NEWS_SOURCES) - len(errors)
        status = "ok"
        if errors and sources_updated == 0:
            status = "error"
        elif errors:
            status = "partial"

        return {
            "status": status,
            "fetched": total_fetched,
            "inserted": total_inserted,
            "duplicate": total_duplicate,
            "errors": errors,
            "sources_updated": sources_updated,
        }

    def _write_item(self, item: NewsBoardItem) -> None:
        """Write a single normalized item to Redis."""
        raw = self._cache
        if not raw.is_redis_available:
            return

        event_ts = (item.event_time or item.published_at or utc_now()).timestamp()
        expiry_ts = event_ts + 86400  # +24h

        item_json = item.model_dump(mode="json")

        raw.set(f"{KEY_ITEM_PREFIX}{item.id}", item_json, ttl=None)
        raw.expireat(f"{KEY_ITEM_PREFIX}{item.id}", expiry_ts)

        raw.zadd(KEY_INDEX_ZSET, {item.id: event_ts})

        fps = self.build_news_fingerprints(item)
        # Store title-only fingerprint
        if fps.get("title"):
            title_fp_key = f"{KEY_FINGERPRINT_PREFIX}title:{fps['title']}"
            raw.set(title_fp_key, item.id, ttl=None)
            raw.expireat(title_fp_key, expiry_ts)
        # Store full and entity fingerprints
        for fp_key in (fps.get("full"), fps.get("entity")):
            if not fp_key:
                continue
            abs_fp_key = f"{KEY_FINGERPRINT_PREFIX}{fp_key}"
            raw.set(abs_fp_key, item.id, ttl=None)
            raw.expireat(abs_fp_key, expiry_ts)
            raw.zadd(KEY_FINGERPRINT_ZSET, {fp_key: event_ts})

        if fps.get("entity"):
            entity_bucket = int(event_ts // ENTITY_BUCKET_SECONDS)
            entity_bucket_fp = f"{fps['entity']}:{entity_bucket}"
            entity_bucket_key = f"{KEY_FINGERPRINT_PREFIX}{entity_bucket_fp}"
            raw.set(entity_bucket_key, item.id, ttl=None)
            raw.expireat(entity_bucket_key, expiry_ts)
            raw.zadd(KEY_FINGERPRINT_ZSET, {entity_bucket_fp: event_ts})

        # Near-duplicate fingerprint
        normalized = self._strip_title_markers(item.title)
        if len(normalized) >= 12:
            near_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:24]
            time_bucket = int(event_ts // NEAR_BUCKET_SECONDS)
            near_key = f"{FINGERPRINT_KEY_SIM}{near_hash}:{time_bucket}"
            raw.set(near_key, item.id, ttl=None)
            raw.expireat(near_key, expiry_ts)

    def _store_status(self, result: dict[str, Any], *, now: datetime) -> None:
        """Store the latest update result as status."""
        status = {
            "last_update": now.isoformat(),
            "total_fetched": result.get("fetched", 0),
            "total_inserted": result.get("inserted", 0),
            "total_duplicate": result.get("duplicate", 0),
            "source_watermarks": {},
            "error_sources": result.get("errors", []),
            "status": result.get("status", "unknown"),
        }
        for src, _ in TUSHARE_NEWS_SOURCES:
            wm = self._cache.get(f"{KEY_SYNC_PREFIX}{src}")
            if wm:
                status["source_watermarks"][src] = wm
        self._cache.set(STATUS_KEY, status, ttl=86400)


# ------------------------------------------------------------------
# Shared helper functions (used by both API and service)
# ------------------------------------------------------------------


def _parse_datetime(value: Any) -> datetime | None:
    from email.utils import parsedate_to_datetime

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
    naive = parsed.replace(tzinfo=None)
    return naive.replace(tzinfo=CHINA_TZ).astimezone(timezone.utc)


def _title_from_content(content: str) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    if not text:
        return ""
    sentence = re.split(r"[。！？!?]\s*", text, maxsplit=1)[0].strip()
    return (sentence or text)[:80]


def _infer_category(text: str) -> str:
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword.lower() in text.lower() for keyword in keywords):
            return category
    return "us_market" if re.search(r"\b(NVDA|TSLA|AAPL|MSFT|META|AMZN|GOOGL)\b", text, re.I) else "price"


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


def _infer_sentiment(text: str) -> str:
    if any(keyword in text for keyword in NEGATIVE_KEYWORDS):
        return "negative"
    if any(keyword in text for keyword in POSITIVE_KEYWORDS):
        return "positive"
    return "neutral"


def _stable_id(*, title: str, source: str, published_at: datetime) -> str:
    raw = f"{title}|{source}|{published_at.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _source_label(value: Any) -> str:
    text = str(value or "").strip()
    return TUSHARE_SOURCE_LABELS.get(text, text or "消息")


def _redis_member_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _infer_attention_level(title: str, summary: str) -> str:
    text = f"{title} {summary}"
    high_keywords = ("黄仁勋", "马斯克", "特朗普", "英伟达", "涨停", "跌停", "大涨", "大跌", "监管", "政策", "关税", "突发", "财联社", "金十数据")
    medium_keywords = ("AI", "芯片", "半导体", "机器人", "美股", "创新药", "暴雨", "台风", "厄尔尼诺")
    hit_count = sum(1 for keyword in high_keywords if keyword in text)
    if hit_count >= 2 or len(summary or "") >= 180:
        return "高，具备跨市场或板块扩散条件"
    if hit_count == 1 or any(keyword.lower() in text.lower() for keyword in medium_keywords):
        return "中，需要观察同题材多源扩散"
    return "低，暂按单条快讯观察"
