"""Entity resolver - extracts entities and maps to local stock database."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from .schemas import EntityType, ResolvedEntity

logger = logging.getLogger(__name__)

OVERSEAS_COMPANIES: dict[str, dict[str, str]] = {
    "苹果": {"name": "Apple", "ticker": "AAPL"},
    "apple": {"name": "Apple", "ticker": "AAPL"},
    "英伟达": {"name": "NVIDIA", "ticker": "NVDA"},
    "nvidia": {"name": "NVIDIA", "ticker": "NVDA"},
    "特斯拉": {"name": "Tesla", "ticker": "TSLA"},
    "tesla": {"name": "Tesla", "ticker": "TSLA"},
    "微软": {"name": "Microsoft", "ticker": "MSFT"},
    "microsoft": {"name": "Microsoft", "ticker": "MSFT"},
    "谷歌": {"name": "Google", "ticker": "GOOGL"},
    "google": {"name": "Google", "ticker": "GOOGL"},
    "亚马逊": {"name": "Amazon", "ticker": "AMZN"},
    "amazon": {"name": "Amazon", "ticker": "AMZN"},
    "meta": {"name": "Meta", "ticker": "META"},
    "台积电": {"name": "TSMC", "ticker": "TSM"},
    "tsmc": {"name": "TSMC", "ticker": "TSM"},
    "三星": {"name": "Samsung", "ticker": "005930.KS"},
    "samsung": {"name": "Samsung", "ticker": "005930.KS"},
    "美光": {"name": "Micron", "ticker": "MU"},
    "micron": {"name": "Micron", "ticker": "MU"},
    "博通": {"name": "Broadcom", "ticker": "AVGO"},
    "broadcom": {"name": "Broadcom", "ticker": "AVGO"},
    "amd": {"name": "AMD", "ticker": "AMD"},
    "超威": {"name": "AMD", "ticker": "AMD"},
    "英特尔": {"name": "Intel", "ticker": "INTC"},
    "intel": {"name": "Intel", "ticker": "INTC"},
    "高通": {"name": "Qualcomm", "ticker": "QCOM"},
    "qualcomm": {"name": "Qualcomm", "ticker": "QCOM"},
    "arm": {"name": "ARM", "ticker": "ARM"},
    "安谋": {"name": "ARM", "ticker": "ARM"},
    "阿斯麦": {"name": "ASML", "ticker": "ASML"},
    "asml": {"name": "ASML", "ticker": "ASML"},
    "应用材料": {"name": "Applied Materials", "ticker": "AMAT"},
    "泛林": {"name": "Lam Research", "ticker": "LRCX"},
    "东京电子": {"name": "Tokyo Electron", "ticker": "TOELY"},
    "sk海力士": {"name": "SK Hynix", "ticker": "000660.KS"},
    "礼来": {"name": "Eli Lilly", "ticker": "LLY"},
    "eli lilly": {"name": "Eli Lilly", "ticker": "LLY"},
    "诺和诺德": {"name": "Novo Nordisk", "ticker": "NVO"},
    "novo nordisk": {"name": "Novo Nordisk", "ticker": "NVO"},
    "辉瑞": {"name": "Pfizer", "ticker": "PFE"},
    "pfizer": {"name": "Pfizer", "ticker": "PFE"},
    "默沙东": {"name": "Merck", "ticker": "MRK"},
    "merck": {"name": "Merck", "ticker": "MRK"},
    "强生": {"name": "Johnson & Johnson", "ticker": "JNJ"},
    "艾伯维": {"name": "AbbVie", "ticker": "ABBV"},
    "阿斯利康": {"name": "AstraZeneca", "ticker": "AZN"},
    "罗氏": {"name": "Roche", "ticker": "RHHBY"},
    "诺华": {"name": "Novartis", "ticker": "NVS"},
    "赛诺菲": {"name": "Sanofi", "ticker": "SNY"},
    "吉利德": {"name": "Gilead", "ticker": "GILD"},
    "安进": {"name": "Amgen", "ticker": "AMGN"},
    "福泰": {"name": "Vertex", "ticker": "VRTX"},
    "莫德纳": {"name": "Moderna", "ticker": "MRNA"},
    "biontech": {"name": "BioNTech", "ticker": "BNTX"},
    "渤健": {"name": "Biogen", "ticker": "BIIB"},
}

COMMODITY_KEYWORDS: dict[str, str] = {
    "白银": "白银",
    "银价": "白银",
    "现货白银": "白银",
    "黄金": "黄金",
    "金价": "黄金",
    "现货黄金": "黄金",
    "铜": "铜",
    "铜价": "铜",
    "原油": "原油",
    "油价": "原油",
    "石油": "原油",
    "贵金属": "贵金属",
    "基本金属": "基本金属",
    "大宗商品": "大宗商品",
}

INDUSTRY_KEYWORDS: dict[str, str] = {
    "南京港": "南京港",
    "港口航运": "港口航运",
    "港口": "港口航运",
    "航运": "港口航运",
    "国际航线": "港口航运",
    "外贸物流": "港口航运",
    "集装箱": "港口航运",
    "多式联运": "港口航运",
    "跨境物流": "物流运输",
    "物流": "物流运输",
}


class EntityResolver:
    """实体识别器 - 抽取实体并映射到本地股票库。"""

    def resolve(self, text: str, evidence_list: list[dict[str, Any]],
                db: Optional[Session] = None) -> list[ResolvedEntity]:
        entities: list[ResolvedEntity] = []
        seen_names: set[str] = set()

        for company_name, info in OVERSEAS_COMPANIES.items():
            if company_name.lower() in text.lower():
                if company_name.lower() in seen_names:
                    continue
                seen_names.add(company_name.lower())
                entities.append(ResolvedEntity(
                    entity_type=EntityType.COMPANY_ENTITY,
                    name=info["name"],
                    matched_code=info.get("ticker"),
                    matched_name=info["name"],
                    is_overseas=True,
                    confidence=0.95,
                ))

        for kw, commodity_name in COMMODITY_KEYWORDS.items():
            if kw in text and commodity_name.lower() not in seen_names:
                seen_names.add(commodity_name.lower())
                entities.append(ResolvedEntity(
                    entity_type=EntityType.COMMODITY_ENTITY,
                    name=commodity_name,
                    matched_code=None,
                    matched_name=commodity_name,
                    is_overseas=False,
                    confidence=0.9,
                ))

        for kw, industry_name in INDUSTRY_KEYWORDS.items():
            if kw in text and industry_name.lower() not in seen_names:
                seen_names.add(industry_name.lower())
                entities.append(ResolvedEntity(
                    entity_type=EntityType.INDUSTRY_ENTITY,
                    name=industry_name,
                    matched_code=None,
                    matched_name=industry_name,
                    is_overseas=False,
                    confidence=0.88,
                ))

        if db:
            local_entities = self._resolve_from_db(text, db, seen_names)
            entities.extend(local_entities)

        return entities

    def _resolve_from_db(self, text: str, db: Session,
                          seen_names: set[str]) -> list[ResolvedEntity]:
        entities: list[ResolvedEntity] = []
        try:
            from app.models import Stock

            keywords = self._extract_keywords(text)
            if not keywords:
                return entities

            stocks = (
                db.query(Stock)
                .filter(
                    Stock.name.in_(keywords)
                    | Stock.code.in_([f"{k}.SZ" for k in keywords]
                                     + [f"{k}.SH" for k in keywords])
                )
                .limit(20)
                .all()
            )

            for stock in stocks:
                name = stock.name or ""
                code = stock.code or ""
                if name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())

                entities.append(ResolvedEntity(
                    entity_type=EntityType.STOCK_ENTITY,
                    name=name,
                    matched_code=code,
                    matched_name=name,
                    is_overseas=False,
                    confidence=0.85,
                ))
        except Exception as exc:
            logger.warning("EntityResolver DB 查询失败: %s", exc)

        return entities

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        import re
        found = set()
        for match in re.finditer(r"(?:[\u4e00-\u9fff]{2,6}(?:科技|股份|集团|控股|电子|通信|医药|能源|汽车|银行)?)", text):
            word = match.group(0)
            if len(word) >= 3:
                found.add(word)
        return list(found)[:10]


entity_resolver = EntityResolver()
