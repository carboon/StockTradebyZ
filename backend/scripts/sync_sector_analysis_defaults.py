"""Sync default sector-analysis config into the database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database import get_db_context
from backend.app.models import Config


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
    "ai-compute": {
        "中际旭创": "300308",
        "新易盛": "300502",
        "寒武纪": "688256",
        "澜起科技": "688008",
        "中科曙光": "603019",
        "科大讯飞": "002230",
        "海康威视": "002415",
        "豪威集团": "603501",
        "金山办公": "688111",
        "浪潮信息": "000977",
        "润泽科技": "300442",
        "工业富联": "601138",
    },
    "semi-storage": {
        "海光信息": "688041",
        "中芯国际": "688981",
        "北方华创": "002371",
        "兆易创新": "603986",
        "中微公司": "688012",
        "拓荆科技": "688072",
        "紫光国微": "002049",
        "江波龙": "301308",
        "佰维存储": "688525",
        "德明利": "001309",
        "豪威集团": "603501",
        "澜起科技": "688008",
    },
    "robotics": {
        "汇川技术": "300124",
        "拓普集团": "601689",
        "绿的谐波": "688017",
        "双环传动": "002472",
        "大族激光": "002008",
        "科大讯飞": "002230",
        "中控技术": "688777",
        "大华股份": "002236",
        "机器人": "300024",
        "埃斯顿": "002747",
        "雷赛智能": "002979",
        "柯力传感": "603662",
    },
    "power-storage": {
        "宁德时代": "300750",
        "阳光电源": "300274",
        "国电南瑞": "600406",
        "思源电气": "002028",
        "特变电工": "600089",
        "中天科技": "600522",
        "亨通光电": "600487",
        "亿纬锂能": "300014",
        "中国西电": "601179",
        "平高电气": "600312",
        "四方股份": "601126",
        "金盘科技": "688676",
    },
    "strategic-materials": {
        "北方稀土": "600111",
        "中国稀土": "000831",
        "厦门钨业": "600549",
        "盛和资源": "600392",
        "包钢股份": "600010",
        "中国铝业": "601600",
        "华友钴业": "603799",
        "洛阳钼业": "603993",
        "中矿资源": "002738",
        "中钨高新": "000657",
        "赣锋锂业": "002460",
        "天齐锂业": "002466",
    },
    "space-satellite": {
        "中国卫星": "600118",
        "中国卫通": "601698",
        "航天电子": "600879",
        "北方导航": "600435",
        "北斗星通": "002151",
        "华测导航": "300627",
        "中科星图": "688568",
        "臻镭科技": "688270",
        "四维图新": "002405",
        "国博电子": "688375",
        "航天宏图": "688066",
        "超图软件": "300036",
    },
    "low-altitude": {
        "万丰奥威": "002085",
        "天银机电": "300342",
        "洪都航空": "600316",
        "航天彩虹": "002389",
        "中直股份": "600038",
        "中无人机": "688297",
        "华力创通": "300045",
        "应流股份": "603308",
        "中国卫星": "600118",
        "航天电子": "600879",
    },
    "advanced-equipment": {
        "中国船舶": "600150",
        "中国重工": "601989",
        "中国动力": "600482",
        "中船防务": "600685",
        "中船科技": "600072",
        "振华重工": "600320",
        "潍柴重机": "000880",
        "中国海防": "600764",
        "亚星锚链": "601890",
        "天海防务": "300008",
        "徐工机械": "000425",
        "三一重工": "600031",
    },
}


def _dump_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _upsert_config(*, key: str, value: str, description: str, overwrite: bool) -> str:
    with get_db_context() as db:
        row = db.query(Config).filter(Config.key == key).first()
        if row is None:
            db.add(Config(key=key, value=value, description=description))
            return "inserted"
        if overwrite:
            row.value = value
            row.description = description
            return "updated"
        return "skipped"


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync default sector-analysis config into configs table")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing config values")
    args = parser.parse_args()

    actions = {
        "sector_analysis_catalog": _upsert_config(
            key="sector_analysis_catalog",
            value=_dump_json(DEFAULT_SECTOR_ANALYSIS_CATALOG),
            description="板块分析目录默认配置",
            overwrite=args.overwrite,
        ),
        "sector_analysis_pool": _upsert_config(
            key="sector_analysis_pool",
            value=_dump_json(DEFAULT_SECTOR_ANALYSIS_POOL),
            description="板块分析股票池默认配置",
            overwrite=args.overwrite,
        ),
    }

    print(json.dumps(actions, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
