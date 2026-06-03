#!/usr/bin/env python3
"""Batch re-score value_lowland_profiles using DeepSeek with scarcity framework.

Reads profiles that need scoring (focus=0, scarcity=0, cycle=other),
sends them to DeepSeek in batches of 15, updates the database.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/backend")

from app.database import SessionLocal
from app.models import Config, Stock, ValueLowlandProfile
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("repair")

BATCH_SIZE = 15
DEEPSEEK_API_KEY = None  # loaded from DB in run()

SYSTEM_PROMPT = """你是一个A股行业稀缺性分析专家。请严格按照以下「行业稀缺性五层壁垒分析框架」对每只股票进行打分。

稀缺性核心定义：供给端存在难以复制的壁垒，使公司在行业中具备不可替代的卡位。

=== 五层壁垒分析 ===

第1层 行政/牌照壁垒（最硬）：
- 需要稀缺牌照/特许经营权？（免税、核电、军工保密、金融全牌照…）
- 新牌照是否冻结？行业是否"只减不增"？
- 是否绑定国家管控的不可再生资源？

第2层 自然资源/地理垄断：
- 不可迁移的地理卡位（盐湖/矿山/港口/水电站）
- 储量+成本双重优势（位于成本曲线左端）
- 检验：去掉它，国内/全球找不到同等替代？

第3层 技术&Know-how壁垒：
- 不是看专利数量，而是看：高良率+长期稳定性+失败成本极高
- 是否已进入下游BOM清单？是否过了客户认证？切换成本多高？

第4层 竞争格局卡位：
- CR3/CR5集中度越高越稀缺
- 老大份额在扩张还是萎缩？
- 定价权：成本上涨时能不能顺价？降价是否引发价格战？

第5层 品牌/生态/网络效应（最软但最持久）：
- 品牌心智独占（茅台/片仔癀）→ 替代品不存在
- 网络效应（用户越多越好用）
- 转换成本钉死（企业软件）

=== 量化验证指标 ===
- 毛利率显著高于同行（>均值+5pct）= 定价权
- ROE/ROIC 持续>15% = 稀缺产生超额回报
- 自由现金流/净利润 > 1 = 赚真钱

=== 六问打分卡 ===
□ 去掉它，行业是不是会"卡壳"？
□ 新玩家进来要跨什么坎？（钱/牌照/十年积累/客户信任）
□ 毛利率是否系统性高于同行且能维持？
□ 高毛利靠"当下周期红利"还是"结构性壁垒"？
□ 三年后壁垒更强还是更弱？
□ 行业增速归零，还能不能赚钱？

得分映射：6问全✓→90-100分；5✓→75-89分；4✓→60-74分；3✓→45-59分；2✓→30-44分；≤1✓→0-29分

=== 输出格式 ===
必须输出纯JSON数组，每只股票一个object：
[{"code":"XXXXXX","business_focus_score":0-100,"scarcity_score":0-100,
  "cycle_type":"resource|chemical|military|energy|utility|other",
  "scarcity_reason":"30字以内总结稀缺性来源"},
 ...]
"""


def make_user_prompt(batch: list[dict]) -> str:
    lines = ["请分析以下股票的主营稀缺性和周期属性：\n"]
    for s in batch:
        lines.append(
            f"|{s['code']}|{s['name']}|{s['industry']}|{s['ownership_type']}|"
            f"{s['controller'][:30]}|{s['main_business'][:120]}|"
        )
    return "\n".join(lines)


def parse_response(content: str) -> list[dict]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Try to find JSON array
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
        raise


def run():
    db = SessionLocal()

    # Load API key from DB config
    api_key = db.query(Config.value).filter(Config.key == "deepseek_api_key").scalar()
    if not api_key:
        log.error("deepseek_api_key not found in DB configs table")
        sys.exit(1)

    client = OpenAI(api_key=str(api_key).strip(), base_url="https://api.deepseek.com")

    # Find profiles needing re-score
    profiles = (
        db.query(ValueLowlandProfile, Stock)
        .join(Stock, Stock.code == ValueLowlandProfile.code)
        .filter(
            (ValueLowlandProfile.business_focus_score == 0) |
            (ValueLowlandProfile.business_focus_score.is_(None)) |
            (ValueLowlandProfile.scarcity_score == 0) |
            (ValueLowlandProfile.scarcity_score.is_(None)) |
            (ValueLowlandProfile.cycle_type == "other")
        )
        .all()
    )

    batch_input = []
    for vp, st in profiles:
        if vp.main_business and vp.main_business.strip():
            batch_input.append({
                "code": vp.code,
                "name": st.name or "",
                "industry": st.industry or "",
                "ownership_type": vp.ownership_type or "unknown",
                "controller": vp.controller or "",
                "main_business": vp.main_business.strip(),
            })

    log.info("Found %d profiles needing re-score (%d with main_business)",
             len(profiles), len(batch_input))

    total = len(batch_input)
    updated = 0
    failed = 0

    for i in range(0, total, BATCH_SIZE):
        batch = batch_input[i:i + BATCH_SIZE]
        log.info("Batch %d/%d (%d stocks)", i // BATCH_SIZE + 1,
                 (total + BATCH_SIZE - 1) // BATCH_SIZE, len(batch))

        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": make_user_prompt(batch)},
                ],
            )
            content = resp.choices[0].message.content
            results = parse_response(content)

            if isinstance(results, dict) and "results" in results:
                results = results["results"]
            if isinstance(results, dict) and "items" in results:
                results = results["items"]
            if isinstance(results, dict):
                results = [results]

            for item in results:
                code = str(item.get("code", "")).zfill(6)
                profile = db.query(ValueLowlandProfile).filter(
                    ValueLowlandProfile.code == code
                ).first()
                if not profile:
                    continue

                focus = float(item.get("business_focus_score", item.get("focus_score", 70)))
                scarcity = float(item.get("scarcity_score", item.get("scarcity", 50)))
                cycle = str(item.get("cycle_type", "other")).strip().lower()
                reason = str(item.get("scarcity_reason", ""))

                if cycle not in ("resource", "chemical", "military", "energy", "utility", "other"):
                    cycle = "other"

                profile.business_focus_score = max(0, min(100, focus))
                profile.scarcity_score = max(0, min(100, scarcity))
                profile.cycle_type = cycle
                profile.updated_at = datetime.now(timezone.utc)
                updated += 1
                log.debug("  %s %s: focus=%.0f scarcity=%.0f cycle=%s %s",
                          code, profile.main_business[:20] if profile.main_business else "-",
                          focus, scarcity, cycle, reason[:30])

            db.commit()
            time.sleep(1)

        except Exception as exc:
            db.rollback()
            failed += len(batch)
            log.error("Batch failed: %s", exc)
            time.sleep(3)

    db.close()
    log.info("Done: %d updated, %d failed, %d total", updated, failed, total)


if __name__ == "__main__":
    run()
