"""
Closing Analysis Service
~~~~~~~~~~~~~~~~~~~~~~~~
生成并读取收盘分析日报。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AnalysisResult, Candidate, ClosingAnalysisReport, Config, Stock, StockDaily
from app.services.deepseek_service import DeepSeekService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now


@dataclass(frozen=True)
class ClosingAnalysisStatus:
    latest_data_date: date | None
    report_trade_date: date | None
    has_report: bool
    can_generate: bool
    status: str
    message: str


class ClosingAnalysisService:
    """基于本地日线、候选池和资金流字段生成收盘日报。"""

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()
        self.deepseek_service = DeepSeekService(api_key=self._load_deepseek_api_key())

    def _load_deepseek_api_key(self) -> str:
        value = self.db.query(Config.value).filter(Config.key == "deepseek_api_key").scalar()
        return str(value or "").strip()

    def get_status(self) -> ClosingAnalysisStatus:
        latest_data_date = self._latest_data_date()
        latest_report = self._latest_report()
        if latest_data_date is None:
            return ClosingAnalysisStatus(None, latest_report.trade_date if latest_report else None, False, False, "no_data", "暂无日线数据，无法生成收盘分析")

        report = self._get_report(latest_data_date)
        if report:
            return ClosingAnalysisStatus(latest_data_date, report.trade_date, True, False, "ready", "当日收盘分析已生成")

        return ClosingAnalysisStatus(latest_data_date, latest_report.trade_date if latest_report else None, False, True, "not_ready", "最新收盘数据已有更新，可生成收盘分析")

    def get_latest_report_payload(self) -> dict[str, Any]:
        latest_data_date = self._latest_data_date()
        if latest_data_date is not None:
            report = self._get_report(latest_data_date)
            if report:
                return self._report_to_payload(report, generated=False, message="当日收盘分析已生成")

        latest_report = self._latest_report()
        if latest_report:
            return self._report_to_payload(latest_report, generated=False, message="展示最近一次收盘分析")

        return {
            "has_report": False,
            "generated": False,
            "message": "暂无收盘分析，请点击生成",
        }

    def generate_report(self, *, user_id: int | None, is_admin: bool, force: bool = False) -> dict[str, Any]:
        latest_data_date = self._latest_data_date()
        if latest_data_date is None:
            return {"has_report": False, "generated": False, "status": "no_data", "message": "暂无日线数据，无法生成收盘分析"}

        existing = self._get_report(latest_data_date)
        if existing and not (is_admin and force):
            return self._report_to_payload(existing, generated=False, message="当日收盘分析已生成，无需重复生成")

        payload = self._build_report(latest_data_date)
        if existing:
            existing.report_json = payload
            existing.generated_by_user_id = user_id
            existing.force_generated = bool(force)
            existing.updated_at = utc_now()
            report = existing
        else:
            report = ClosingAnalysisReport(
                trade_date=latest_data_date,
                source_data_date=latest_data_date,
                status="ready",
                report_json=payload,
                generated_by_user_id=user_id,
                force_generated=bool(force),
            )
            self.db.add(report)

        self.db.commit()
        self.db.refresh(report)
        return self._report_to_payload(report, generated=True, message="收盘分析已生成")

    def _latest_data_date(self) -> date | None:
        return self.db.query(func.max(StockDaily.trade_date)).scalar()

    def _latest_report(self) -> ClosingAnalysisReport | None:
        return self.db.query(ClosingAnalysisReport).order_by(ClosingAnalysisReport.trade_date.desc()).first()

    def _get_report(self, trade_date: date) -> ClosingAnalysisReport | None:
        return self.db.query(ClosingAnalysisReport).filter(ClosingAnalysisReport.trade_date == trade_date).first()

    def _build_report(self, trade_date: date) -> dict[str, Any]:
        previous_trade_date = (
            self.db.query(func.max(StockDaily.trade_date))
            .filter(StockDaily.trade_date < trade_date)
            .scalar()
        )
        return {
            "trade_date": trade_date.isoformat(),
            "source_data_date": trade_date.isoformat(),
            "generated_at": utc_now().isoformat(),
            "market": self._build_market_overview(trade_date, previous_trade_date),
            "sector_flow": self._build_sector_flow(trade_date),
            "candidate_buckets": self._build_candidate_buckets(trade_date),
            "tomorrow_prediction": self._build_tomorrow_prediction(trade_date),
        }

    def _build_market_overview(self, trade_date: date, previous_trade_date: date | None) -> dict[str, Any]:
        rows = self.db.query(StockDaily.code, StockDaily.close).filter(StockDaily.trade_date == trade_date).all()
        current = {code: close for code, close in rows if close is not None}
        previous: dict[str, float] = {}
        if previous_trade_date:
            previous = {
                code: close
                for code, close in self.db.query(StockDaily.code, StockDaily.close).filter(StockDaily.trade_date == previous_trade_date).all()
                if close is not None and close > 0
            }

        changes = [
            (current[code] - previous[code]) / previous[code] * 100
            for code in current.keys() & previous.keys()
            if previous[code] > 0
        ]
        up_count = sum(1 for value in changes if value > 0)
        down_count = sum(1 for value in changes if value < 0)
        flat_count = len(changes) - up_count - down_count
        avg_change_pct = round(sum(changes) / len(changes), 2) if changes else None
        up_ratio = up_count / len(changes) if changes else 0
        if avg_change_pct is None:
            trend = "暂无对照数据"
        elif avg_change_pct >= 0.8 or up_ratio >= 0.62:
            trend = "偏强"
        elif avg_change_pct <= -0.8 or up_ratio <= 0.38:
            trend = "偏弱"
        else:
            trend = "震荡"

        return {
            "trend": trend,
            "trade_date": trade_date.isoformat(),
            "previous_trade_date": previous_trade_date.isoformat() if previous_trade_date else None,
            "avg_change_pct": avg_change_pct,
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
            "total_count": len(changes),
            "summary": f"全市场均值涨跌 {avg_change_pct:.2f}%，上涨 {up_count} 家、下跌 {down_count} 家" if avg_change_pct is not None else "暂无前一交易日对照数据",
        }

    def _build_sector_flow(self, trade_date: date) -> dict[str, list[dict[str, Any]]]:
        rows = (
            self.db.query(Stock.industry, func.sum(func.coalesce(StockDaily.net_mf_amount, 0.0)))
            .join(StockDaily, StockDaily.code == Stock.code)
            .filter(StockDaily.trade_date == trade_date)
            .group_by(Stock.industry)
            .all()
        )
        items = [
            {"sector_name": industry or "未分类", "net_mf_amount": round(float(amount or 0.0), 2)}
            for industry, amount in rows
        ]
        inflow = sorted([item for item in items if item["net_mf_amount"] > 0], key=lambda item: item["net_mf_amount"], reverse=True)[:3]
        outflow = sorted([item for item in items if item["net_mf_amount"] < 0], key=lambda item: item["net_mf_amount"])[:3]
        return {"inflow_top3": inflow, "outflow_top3": outflow}

    def _build_candidate_buckets(self, trade_date: date) -> list[dict[str, Any]]:
        pick_dates = [
            item[0]
            for item in (
                self.db.query(Candidate.pick_date)
                .filter(Candidate.pick_date < trade_date)
                .distinct()
                .order_by(Candidate.pick_date.desc())
                .limit(2)
                .all()
            )
        ]
        return [self._build_candidate_bucket(trade_date, pick_date, index + 1) for index, pick_date in enumerate(pick_dates)]

    def _build_candidate_bucket(self, trade_date: date, pick_date: date, offset: int) -> dict[str, Any]:
        candidate_rows = (
            self.db.query(Candidate, Stock)
            .join(Stock, Stock.code == Candidate.code)
            .filter(Candidate.pick_date == pick_date)
            .all()
        )
        codes = [candidate.code for candidate, _stock in candidate_rows]
        latest_prices = self._price_map(codes, trade_date)
        base_prices = self._price_map(codes, pick_date)

        rising: list[dict[str, Any]] = []
        falling: list[dict[str, Any]] = []
        for candidate, stock in candidate_rows:
            base_close = base_prices.get(candidate.code) or candidate.close_price
            latest_close = latest_prices.get(candidate.code)
            if not base_close or not latest_close or base_close <= 0:
                continue
            change_pct = round((latest_close - base_close) / base_close * 100, 2)
            if change_pct < 5 and change_pct > -5:
                continue
            item = {
                "code": candidate.code,
                "name": stock.name,
                "sector_names": [stock.industry] if stock.industry else [],
                "base_close": round(float(base_close), 3),
                "latest_close": round(float(latest_close), 3),
                "change_pct": change_pct,
                "source_pick_date": pick_date.isoformat(),
            }
            if change_pct >= 5:
                rising.append(item)
            else:
                falling.append(item)

        rising.sort(key=lambda item: item["change_pct"], reverse=True)
        falling.sort(key=lambda item: item["change_pct"])
        return {
            "label": "前日候选" if offset == 1 else "前前日候选",
            "source_pick_date": pick_date.isoformat(),
            "rising": rising,
            "falling": falling,
        }

    def _price_map(self, codes: list[str], trade_date: date) -> dict[str, float]:
        if not codes:
            return {}
        rows = (
            self.db.query(StockDaily.code, StockDaily.close)
            .filter(StockDaily.trade_date == trade_date, StockDaily.code.in_(codes))
            .all()
        )
        return {code: float(close) for code, close in rows if close is not None}

    def _build_tomorrow_prediction(self, trade_date: date) -> dict[str, Any]:
        rows = (
            self.db.query(Candidate, Stock, StockDaily, AnalysisResult)
            .join(Stock, Stock.code == Candidate.code)
            .join(StockDaily, (StockDaily.code == Candidate.code) & (StockDaily.trade_date == trade_date))
            .outerjoin(
                AnalysisResult,
                (AnalysisResult.code == Candidate.code)
                & (AnalysisResult.pick_date == Candidate.pick_date)
                & (AnalysisResult.reviewer == "quant"),
            )
            .filter(Candidate.pick_date == trade_date)
            .all()
        )
        if not rows:
            return {
                "trade_date": trade_date.isoformat(),
                "status": "no_candidates",
                "message": "当日暂无候选股票，无法生成明日预测",
                "preselected": [],
                "selected": [],
            }

        sector_flow_history = self._build_sector_flow_history(trade_date, days=5)
        latest_flow = sector_flow_history[0]["sectors"] if sector_flow_history else {}
        three_day_flow = self._aggregate_sector_flow(sector_flow_history[:3])
        outflow_sectors = {
            item["sector_name"]
            for item in sorted(
                [{"sector_name": name, "net_mf_amount": value} for name, value in latest_flow.items()],
                key=lambda item: item["net_mf_amount"],
            )[:8]
            if item["net_mf_amount"] < 0
        }
        previous_date = (
            self.db.query(func.max(StockDaily.trade_date))
            .filter(StockDaily.trade_date < trade_date)
            .scalar()
        )
        codes = [candidate.code for candidate, *_ in rows]
        previous_prices = self._price_map(codes, previous_date) if previous_date else {}

        scored: list[dict[str, Any]] = []
        for candidate, stock, daily, analysis in rows:
            industry = stock.industry or "未分类"
            prev_close = previous_prices.get(candidate.code)
            change_pct = (daily.close - prev_close) / prev_close * 100 if prev_close else None
            sector_latest = float(latest_flow.get(industry, 0.0))
            sector_three_day = float(three_day_flow.get(industry, 0.0))
            b1_score = float(analysis.total_score) if analysis and analysis.total_score is not None else (65.0 if candidate.b1_passed else 45.0)
            turnover_rate = float(daily.turnover_rate or candidate.turnover or 0.0)
            volume_ratio = float(daily.volume_ratio or 0.0)
            local_score = self._score_tomorrow_candidate(
                b1_score=b1_score,
                sector_latest=sector_latest,
                sector_three_day=sector_three_day,
                in_outflow_sector=industry in outflow_sectors,
                change_pct=change_pct,
                turnover_rate=turnover_rate,
                volume_ratio=volume_ratio,
                b1_passed=bool(candidate.b1_passed),
            )
            scored.append({
                "code": candidate.code,
                "name": stock.name,
                "sector_names": [industry] if industry else [],
                "b1_score": round(b1_score, 2),
                "b1_passed": candidate.b1_passed,
                "b1_comment": analysis.comment if analysis else None,
                "signal_type": analysis.signal_type if analysis else None,
                "verdict": analysis.verdict if analysis else None,
                "close_price": round(float(daily.close), 3) if daily.close is not None else None,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "turnover_rate": round(turnover_rate, 2) if turnover_rate else None,
                "volume_ratio": round(volume_ratio, 2) if volume_ratio else None,
                "sector_net_mf_amount": round(sector_latest, 2),
                "sector_3d_net_mf_amount": round(sector_three_day, 2),
                "local_score": round(local_score, 2),
                "local_reasons": self._build_local_reasons(
                    industry=industry,
                    b1_score=b1_score,
                    sector_latest=sector_latest,
                    sector_three_day=sector_three_day,
                    in_outflow_sector=industry in outflow_sectors,
                    change_pct=change_pct,
                    turnover_rate=turnover_rate,
                    volume_ratio=volume_ratio,
                    b1_passed=bool(candidate.b1_passed),
                ),
            })

        preselected = sorted(scored, key=lambda item: item["local_score"], reverse=True)[:20]
        ai_result = self._ai_filter_tomorrow_prediction(trade_date, preselected, sector_flow_history)
        selected = self._merge_ai_prediction(preselected, ai_result)
        return {
            "trade_date": trade_date.isoformat(),
            "status": "ready" if ai_result.get("enabled") else "ai_unavailable",
            "message": ai_result.get("message") or "明日预测已生成",
            "sector_flow_history": sector_flow_history,
            "preselected": preselected,
            "selected": selected[:10],
            "ai": ai_result,
        }

    def _score_tomorrow_candidate(
        self,
        *,
        b1_score: float,
        sector_latest: float,
        sector_three_day: float,
        in_outflow_sector: bool,
        change_pct: float | None,
        turnover_rate: float,
        volume_ratio: float,
        b1_passed: bool,
    ) -> float:
        score = min(max(b1_score, 0.0), 100.0) * 0.35
        score += 12.0 if b1_passed else -8.0
        score += min(max(sector_latest / 100000.0, -12.0), 18.0)
        score += min(max(sector_three_day / 250000.0, -12.0), 16.0)
        if in_outflow_sector:
            score -= 18.0
        if change_pct is not None:
            if -1.0 <= change_pct <= 6.0:
                score += 10.0
            elif change_pct > 9.0:
                score -= 8.0
            elif change_pct < -5.0:
                score -= 10.0
            else:
                score += max(min(change_pct, 6.0), -3.0)
        if 1.1 <= volume_ratio <= 3.5:
            score += min(volume_ratio * 4.0, 12.0)
        elif volume_ratio > 5.0:
            score -= 5.0
        if 2.0 <= turnover_rate <= 18.0:
            score += min(turnover_rate * 0.6, 10.0)
        elif turnover_rate > 30.0:
            score -= 6.0
        return score

    def _build_local_reasons(
        self,
        *,
        industry: str,
        b1_score: float,
        sector_latest: float,
        sector_three_day: float,
        in_outflow_sector: bool,
        change_pct: float | None,
        turnover_rate: float,
        volume_ratio: float,
        b1_passed: bool,
    ) -> list[str]:
        reasons = [f"B1{'通过' if b1_passed else '未通过'}，评分 {b1_score:.1f}"]
        if sector_latest > 0:
            reasons.append(f"{industry} 当日资金净流入 {sector_latest:.0f} 万")
        elif sector_latest < 0:
            reasons.append(f"{industry} 当日资金净流出 {abs(sector_latest):.0f} 万")
        if sector_three_day > 0:
            reasons.append(f"{industry} 近3日资金净流入 {sector_three_day:.0f} 万")
        if in_outflow_sector:
            reasons.append("所属板块位于资金流出降级区")
        if change_pct is not None:
            reasons.append(f"当日涨跌 {change_pct:.2f}%")
        if turnover_rate:
            reasons.append(f"换手率 {turnover_rate:.2f}%")
        if volume_ratio:
            reasons.append(f"量比 {volume_ratio:.2f}")
        return reasons

    def _build_sector_flow_history(self, trade_date: date, *, days: int) -> list[dict[str, Any]]:
        trade_dates = [
            item[0]
            for item in (
                self.db.query(StockDaily.trade_date)
                .filter(StockDaily.trade_date <= trade_date)
                .distinct()
                .order_by(StockDaily.trade_date.desc())
                .limit(days)
                .all()
            )
        ]
        history: list[dict[str, Any]] = []
        for item_date in trade_dates:
            flow_rows = (
                self.db.query(Stock.industry, func.sum(func.coalesce(StockDaily.net_mf_amount, 0.0)))
                .join(StockDaily, StockDaily.code == Stock.code)
                .filter(StockDaily.trade_date == item_date)
                .group_by(Stock.industry)
                .all()
            )
            sectors = {industry or "未分类": round(float(amount or 0.0), 2) for industry, amount in flow_rows}
            history.append({"trade_date": item_date.isoformat(), "sectors": sectors})
        return history

    @staticmethod
    def _aggregate_sector_flow(history: list[dict[str, Any]]) -> dict[str, float]:
        result: dict[str, float] = {}
        for item in history:
            sectors = item.get("sectors") or {}
            if not isinstance(sectors, dict):
                continue
            for name, value in sectors.items():
                result[str(name)] = result.get(str(name), 0.0) + float(value or 0.0)
        return result

    def _ai_filter_tomorrow_prediction(
        self,
        trade_date: date,
        preselected: list[dict[str, Any]],
        sector_flow_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not self.deepseek_service.enabled:
            return {"enabled": False, "message": "DeepSeek API Key 未配置，已仅返回本地量化预筛"}

        context = {
            "trade_date": trade_date.isoformat(),
            "rule": "从本地预筛 TOP20 中剔除明显负面消息、缺少利好催化或板块资金明显恶化的股票，最终选出 TOP10。",
            "sector_flow_history": sector_flow_history,
            "candidates": preselected,
            "recent_news": self._matched_news_for_candidates(preselected),
        }
        system_prompt = (
            "你是A股收盘后明日候选股筛选助手。"
            "只能基于提供的结构化上下文与新闻摘要判断，必须输出 JSON object，不能输出 markdown。"
            "如果没有足够利好消息或存在明显负面消息，应降低排名或剔除。"
        )
        user_prompt = (
            "请从 candidates 中选出最终 TOP10。"
            "固定返回 JSON："
            '{"selected":[{"code":"string","rank":1,"ai_score":0,'
            '"bullish_news":["string"],"negative_news":["string"],"ai_comment":"string",'
            '"decision_reason":"string"}],'
            '"rejected":[{"code":"string","reason":"string"}],'
            '"summary":"string","confidence":0}\n'
            f"上下文：\n{json.dumps(context, ensure_ascii=False, default=str)}"
        )
        try:
            result = self.deepseek_service.infer_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.15,
            )
            result["enabled"] = True
            result["message"] = "DeepSeek 已完成 TOP20 到 TOP10 过滤"
            return result
        except Exception as exc:
            return {"enabled": False, "message": f"DeepSeek 明日预测失败：{exc}"}

    def _matched_news_for_candidates(self, preselected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        end_date = utc_now().date()
        start_date = end_date - timedelta(days=14)
        news_items = self.tushare_service.get_news_items(
            src="yicai",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            limit=120,
        )
        keywords: list[str] = []
        for item in preselected:
            keywords.extend([str(item.get("name") or ""), *[str(name) for name in item.get("sector_names") or []]])
        keywords = [item for item in dict.fromkeys(keywords) if item]
        matched: list[dict[str, Any]] = []
        for item in news_items:
            text = f"{item.get('title') or ''} {item.get('content') or ''}"
            if not any(keyword in text for keyword in keywords):
                continue
            matched.append(item)
            if len(matched) >= 40:
                break
        return matched

    @staticmethod
    def _merge_ai_prediction(preselected: list[dict[str, Any]], ai_result: dict[str, Any]) -> list[dict[str, Any]]:
        by_code = {item["code"]: item for item in preselected}
        selected_raw = ai_result.get("selected") if isinstance(ai_result, dict) else None
        merged: list[dict[str, Any]] = []
        if isinstance(selected_raw, list):
            for raw in selected_raw:
                if not isinstance(raw, dict):
                    continue
                code = str(raw.get("code") or "").zfill(6)
                base = by_code.get(code)
                if not base:
                    continue
                merged.append({
                    **base,
                    "rank": int(raw.get("rank") or len(merged) + 1),
                    "ai_score": raw.get("ai_score"),
                    "bullish_news": raw.get("bullish_news") if isinstance(raw.get("bullish_news"), list) else [],
                    "negative_news": raw.get("negative_news") if isinstance(raw.get("negative_news"), list) else [],
                    "ai_comment": raw.get("ai_comment") or raw.get("decision_reason"),
                    "decision_reason": raw.get("decision_reason"),
                })
        if not merged:
            merged = [
                {
                    **item,
                    "rank": index + 1,
                    "ai_score": None,
                    "bullish_news": [],
                    "negative_news": [],
                    "ai_comment": "DeepSeek 未返回可用排序，暂按本地综合分保留",
                    "decision_reason": "本地综合分排序",
                }
                for index, item in enumerate(preselected[:10])
            ]
        return sorted(merged, key=lambda item: item.get("rank") or 999)

    def _report_to_payload(self, report: ClosingAnalysisReport, *, generated: bool, message: str) -> dict[str, Any]:
        data = dict(report.report_json or {})
        data.update({
            "id": report.id,
            "has_report": True,
            "generated": generated,
            "status": report.status,
            "message": message,
            "trade_date": report.trade_date.isoformat(),
            "source_data_date": report.source_data_date.isoformat(),
            "generated_at": report.updated_at.isoformat() if report.updated_at else None,
            "force_generated": report.force_generated,
        })
        return data
