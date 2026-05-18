"""Sector-analysis config defaults and normalization helpers."""
from __future__ import annotations

import json
from typing import Any


DEFAULT_SECTOR_ANALYSIS_CATALOG = {
    "version": 1,
    "menuTitle": "板块分析",
    "defaultSectorKey": "overview",
    "sectors": [
        {
            "key": "ai-compute",
            "name": "AI算力与数据中心",
            "description": "围绕算力扩容、传输升级、数据中心建设和配套环节展开，适合作为AI主线的核心观察池。",
            "policyFocus": ["人工智能+", "智能体", "智算集群", "算电协同"],
            "focusTracks": ["光模块/CPO", "高速连接", "服务器", "液冷", "IDC", "PCB"],
            "industryHints": ["通信", "电子", "计算机设备", "数据中心"],
            "enabled": True,
            "order": 10,
        },
        {
            "key": "semi-storage",
            "name": "半导体与先进存储",
            "description": "覆盖国产替代、先进封装、HBM/存储、设备材料等方向，兼具政策确定性和业绩弹性。",
            "policyFocus": ["集成电路", "国产替代", "先进封装"],
            "focusTracks": ["存储", "设备", "材料", "先进封装", "模拟/算力芯片"],
            "industryHints": ["半导体", "电子元件", "材料"],
            "enabled": True,
            "order": 20,
        },
        {
            "key": "robotics",
            "name": "机器人与智能制造",
            "description": "重点跟踪具身智能与工业自动化的交汇地带，优先关注核心零部件和设备环节。",
            "policyFocus": ["具身智能", "智能制造", "新质生产力"],
            "focusTracks": ["减速器", "伺服", "控制器", "丝杠", "传感器", "机器视觉"],
            "industryHints": ["自动化设备", "专用设备", "工业控制"],
            "enabled": True,
            "order": 30,
        },
        {
            "key": "power-storage",
            "name": "新型电力系统与储能",
            "description": "相比传统发电，更聚焦电网升级、储能、算电协同与源网荷储一体化。",
            "policyFocus": ["新型电力系统", "新型储能", "算电协同"],
            "focusTracks": ["电网设备", "储能电池", "PCS", "温控", "虚拟电厂", "特高压"],
            "industryHints": ["电力设备", "电网自动化", "储能"],
            "enabled": True,
            "order": 40,
        },
        {
            "key": "strategic-materials",
            "name": "战略金属与关键材料",
            "description": "有色里优先看与AI、半导体、高端制造直接耦合的关键材料，而不是单纯周期金属。",
            "policyFocus": ["战略资源", "关键材料", "产业链安全"],
            "focusTracks": ["稀土", "钨", "镓", "铟", "锑", "铜箔", "复合材料"],
            "industryHints": ["有色金属", "新材料", "稀土永磁"],
            "enabled": True,
            "order": 50,
        },
        {
            "key": "space-satellite",
            "name": "商业航天与卫星互联网",
            "description": "从政策推动走向产业化建设，适合中期跟踪卫星制造、地面设备和通信链条。",
            "policyFocus": ["商业航天", "卫星互联网", "空天信息"],
            "focusTracks": ["卫星制造", "地面站", "星载通信", "导航增强", "遥感应用"],
            "industryHints": ["军工电子", "通信设备", "导航定位"],
            "enabled": True,
            "order": 60,
        },
        {
            "key": "low-altitude",
            "name": "低空经济",
            "description": "聚焦飞控、导航通信、核心零部件和基础设施，比泛化题材更容易形成持续跟踪池。",
            "policyFocus": ["低空经济", "空域协同", "基础设施"],
            "focusTracks": ["飞控", "导航通信", "航空结构件", "电驱动", "低空基建"],
            "industryHints": ["通航装备", "导航通信", "航空零部件"],
            "enabled": True,
            "order": 70,
        },
        {
            "key": "advanced-equipment",
            "name": "高端装备与海洋装备",
            "description": "承接高端制造、海洋强国与大国重器主线，适合容纳船舶、能源装备、工程装备等强形态个股。",
            "policyFocus": ["高端装备", "海洋强国", "重大装备"],
            "focusTracks": ["船舶", "海工装备", "能源装备", "大型铸锻件", "军民融合装备"],
            "industryHints": ["船舶制造", "工程机械", "高端装备"],
            "enabled": True,
            "order": 80,
        },
    ],
}

DEFAULT_SECTOR_ANALYSIS_POOL = {
    "ai-compute": [
        {"code": "300308", "name": "中际旭创"},
        {"code": "300502", "name": "新易盛"},
        {"code": "688256", "name": "寒武纪"},
        {"code": "688008", "name": "澜起科技"},
        {"code": "603019", "name": "中科曙光"},
        {"code": "002230", "name": "科大讯飞"},
        {"code": "002415", "name": "海康威视"},
        {"code": "603501", "name": "豪威集团"},
        {"code": "688111", "name": "金山办公"},
        {"code": "000977", "name": "浪潮信息"},
        {"code": "300442", "name": "润泽科技"},
        {"code": "601138", "name": "工业富联"},
    ],
    "semi-storage": [
        {"code": "688041", "name": "海光信息"},
        {"code": "688981", "name": "中芯国际"},
        {"code": "002371", "name": "北方华创"},
        {"code": "603986", "name": "兆易创新"},
        {"code": "688012", "name": "中微公司"},
        {"code": "688072", "name": "拓荆科技"},
        {"code": "002049", "name": "紫光国微"},
        {"code": "301308", "name": "江波龙"},
        {"code": "688525", "name": "佰维存储"},
        {"code": "001309", "name": "德明利"},
        {"code": "603501", "name": "豪威集团"},
        {"code": "688008", "name": "澜起科技"},
    ],
    "robotics": [
        {"code": "300124", "name": "汇川技术"},
        {"code": "601689", "name": "拓普集团"},
        {"code": "688017", "name": "绿的谐波"},
        {"code": "002472", "name": "双环传动"},
        {"code": "002008", "name": "大族激光"},
        {"code": "002230", "name": "科大讯飞"},
        {"code": "688777", "name": "中控技术"},
        {"code": "002236", "name": "大华股份"},
        {"code": "300024", "name": "机器人"},
        {"code": "002747", "name": "埃斯顿"},
        {"code": "002979", "name": "雷赛智能"},
        {"code": "603662", "name": "柯力传感"},
    ],
    "power-storage": [
        {"code": "300750", "name": "宁德时代"},
        {"code": "300274", "name": "阳光电源"},
        {"code": "600406", "name": "国电南瑞"},
        {"code": "002028", "name": "思源电气"},
        {"code": "600089", "name": "特变电工"},
        {"code": "600522", "name": "中天科技"},
        {"code": "600487", "name": "亨通光电"},
        {"code": "300014", "name": "亿纬锂能"},
        {"code": "601179", "name": "中国西电"},
        {"code": "600312", "name": "平高电气"},
        {"code": "601126", "name": "四方股份"},
        {"code": "688676", "name": "金盘科技"},
    ],
    "strategic-materials": [
        {"code": "600111", "name": "北方稀土"},
        {"code": "000831", "name": "中国稀土"},
        {"code": "600549", "name": "厦门钨业"},
        {"code": "600392", "name": "盛和资源"},
        {"code": "600010", "name": "包钢股份"},
        {"code": "601600", "name": "中国铝业"},
        {"code": "603799", "name": "华友钴业"},
        {"code": "603993", "name": "洛阳钼业"},
        {"code": "002738", "name": "中矿资源"},
        {"code": "000657", "name": "中钨高新"},
        {"code": "002460", "name": "赣锋锂业"},
        {"code": "002466", "name": "天齐锂业"},
    ],
    "space-satellite": [
        {"code": "600118", "name": "中国卫星"},
        {"code": "601698", "name": "中国卫通"},
        {"code": "600879", "name": "航天电子"},
        {"code": "600435", "name": "北方导航"},
        {"code": "002151", "name": "北斗星通"},
        {"code": "300627", "name": "华测导航"},
        {"code": "688568", "name": "中科星图"},
        {"code": "688270", "name": "臻镭科技"},
        {"code": "002405", "name": "四维图新"},
        {"code": "688375", "name": "国博电子"},
        {"code": "688066", "name": "航天宏图"},
        {"code": "300036", "name": "超图软件"},
    ],
    "low-altitude": [
        {"code": "002085", "name": "万丰奥威"},
        {"code": "300342", "name": "天银机电"},
        {"code": "600316", "name": "洪都航空"},
        {"code": "002389", "name": "航天彩虹"},
        {"code": "600038", "name": "中直股份"},
        {"code": "688297", "name": "中无人机"},
        {"code": "300045", "name": "华力创通"},
        {"code": "603308", "name": "应流股份"},
        {"code": "600118", "name": "中国卫星"},
        {"code": "600879", "name": "航天电子"},
    ],
    "advanced-equipment": [
        {"code": "600150", "name": "中国船舶"},
        {"code": "601989", "name": "中国重工"},
        {"code": "600482", "name": "中国动力"},
        {"code": "600685", "name": "中船防务"},
        {"code": "600072", "name": "中船科技"},
        {"code": "600320", "name": "振华重工"},
        {"code": "000880", "name": "潍柴重机"},
        {"code": "600764", "name": "中国海防"},
        {"code": "601890", "name": "亚星锚链"},
        {"code": "300008", "name": "天海防务"},
        {"code": "000425", "name": "徐工机械"},
        {"code": "600031", "name": "三一重工"},
    ],
}


def _normalize_code(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").replace("、", ",").split(",") if item.strip()]
    return []


def _normalize_positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _parse_json_payload(raw_value: str | None) -> Any:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _normalize_catalog_entry(value: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    key = str(value.get("key") or "").strip()
    name = str(value.get("name") or "").strip()
    description = str(value.get("description") or "").strip()
    if not key or not name or not description:
        return None

    return {
        "key": key,
        "name": name,
        "description": description,
        "policyFocus": _normalize_string_list(value.get("policyFocus")),
        "focusTracks": _normalize_string_list(value.get("focusTracks")),
        "industryHints": _normalize_string_list(value.get("industryHints")),
        "enabled": value.get("enabled") is not False,
        "order": _normalize_positive_int(value.get("order"), (index + 1) * 10),
    }


def _normalize_catalog_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return DEFAULT_SECTOR_ANALYSIS_CATALOG

    raw_sectors = payload.get("sectors")
    if isinstance(raw_sectors, list):
        sectors = [
            item
            for index, raw_item in enumerate(raw_sectors)
            for item in [_normalize_catalog_entry(raw_item, index)]
            if item and item.get("enabled", True)
        ]
        sectors.sort(key=lambda item: item.get("order", 9999))
    else:
        sectors = DEFAULT_SECTOR_ANALYSIS_CATALOG["sectors"]

    default_sector_key = str(payload.get("defaultSectorKey") or "").strip() or DEFAULT_SECTOR_ANALYSIS_CATALOG["defaultSectorKey"]
    valid_keys = {item["key"] for item in sectors}
    if default_sector_key != "overview" and default_sector_key not in valid_keys:
        default_sector_key = DEFAULT_SECTOR_ANALYSIS_CATALOG["defaultSectorKey"]

    return {
        "version": _normalize_positive_int(payload.get("version"), DEFAULT_SECTOR_ANALYSIS_CATALOG["version"]),
        "menuTitle": str(payload.get("menuTitle") or "").strip() or DEFAULT_SECTOR_ANALYSIS_CATALOG["menuTitle"],
        "defaultSectorKey": default_sector_key,
        "sectors": sectors or DEFAULT_SECTOR_ANALYSIS_CATALOG["sectors"],
    }


def _normalize_pool_record(payload: Any) -> dict[str, list[dict[str, str]]]:
    if not isinstance(payload, dict) or not payload:
        return {}

    top_keys = list(payload.keys())
    if top_keys and all(str(key).strip().isdigit() for key in top_keys):
        return {
            "当前热盘": [
                {
                    "code": _normalize_code(code),
                    "name": str(payload.get(code) or _normalize_code(code)).strip() or _normalize_code(code),
                }
                for code in top_keys
                if _normalize_code(code)
            ]
        }

    normalized: dict[str, list[dict[str, str]]] = {}
    for sector_key, entries in payload.items():
        bucket_key = str(sector_key or "").strip()
        if not bucket_key:
            continue

        items: list[dict[str, str]] = []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                code = _normalize_code(entry.get("code"))
                if not code:
                    continue
                name = str(entry.get("name") or code).strip() or code
                items.append({"code": code, "name": name})
        elif isinstance(entries, dict):
            for raw_name, raw_code in entries.items():
                name_looks_like_code = str(raw_name).strip().isdigit()
                code = _normalize_code(raw_name if name_looks_like_code else raw_code)
                if not code:
                    continue
                name = (
                    str(raw_code if name_looks_like_code else raw_name).strip()
                    or code
                )
                items.append({"code": code, "name": name})

        if items:
            normalized[bucket_key] = items

    return normalized


def resolve_sector_analysis_catalog(raw_value: str | None = None) -> dict[str, Any]:
    return _normalize_catalog_payload(_parse_json_payload(raw_value))


def resolve_sector_stock_pool(
    raw_value: str | None = None,
    fallback_raw_value: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    primary = _normalize_pool_record(_parse_json_payload(raw_value))
    if primary:
        return primary

    fallback = _normalize_pool_record(_parse_json_payload(fallback_raw_value))
    if not fallback:
        return DEFAULT_SECTOR_ANALYSIS_POOL

    merged = dict(DEFAULT_SECTOR_ANALYSIS_POOL)
    merged.update(fallback)
    return merged
