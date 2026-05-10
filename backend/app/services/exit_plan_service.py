"""
Exit Plan Service
~~~~~~~~~~~~~~~~~
MFE 分位目标 + 结构止损 + 移动止盈。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from app.models import StockDaily


DEFAULT_TARGETS: dict[str, dict[str, float]] = {
    "5d": {"p50": 0.060, "p75": 0.102, "p90": 0.173},
    "10d": {"p50": 0.104, "p75": 0.185, "p90": 0.344},
    "20d": {"p50": 0.132, "p75": 0.349, "p90": 0.589},
}

ACTION_LABELS = {
    "hold": "继续持有",
    "wash_observe": "洗盘观察",
    "hold_cautious": "谨慎持有",
    "take_profit_partial": "部分止盈",
    "trim": "减仓",
    "exit": "退出",
}


class ExitPlanService:
    """计算出场计划，不持久化状态。"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or PROJECT_ROOT / "config" / "exit_plan.yaml"
        self.config = self._load_config()
        self.targets = self._load_targets()

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {"fallback_targets": DEFAULT_TARGETS, "risk": {}}
        with self.config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("fallback_targets", DEFAULT_TARGETS)
        data.setdefault("risk", {})
        return data

    def _load_targets(self) -> dict[str, dict[str, float]]:
        profiles_path = Path(str(self.config.get("profiles_path") or "data/exit/exit_profiles.json"))
        if not profiles_path.is_absolute():
            profiles_path = PROJECT_ROOT / profiles_path
        if profiles_path.exists():
            try:
                with profiles_path.open("r", encoding="utf-8") as f:
                    profiles = json.load(f)
                targets = profiles.get("targets") if isinstance(profiles, dict) else None
                if targets is None and isinstance(profiles, dict) and any(period in profiles for period in DEFAULT_TARGETS):
                    targets = profiles
                if targets is None and isinstance(profiles, dict):
                    targets = self._targets_from_backtest_profiles(profiles)
                if isinstance(targets, dict):
                    return self._normalize_targets(targets)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        return self._normalize_targets(self.config.get("fallback_targets") or DEFAULT_TARGETS)

    def _targets_from_backtest_profiles(self, payload: dict[str, Any]) -> Optional[dict[str, dict[str, float]]]:
        profiles = payload.get("profiles")
        if not isinstance(profiles, dict):
            return None

        filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}
        profile_keys = [
            self.config.get("profile_key"),
            "|".join(
                [
                    str(filters.get("strategy") or "b1"),
                    str(filters.get("verdict") or "PASS"),
                    str(filters.get("signal_type") or "trend_start"),
                    str(filters.get("prefilter_status") or "passed"),
                    "all",
                ]
            ),
            "b1|PASS|trend_start|passed|all",
            "b1|all|all|all|all",
            "fallback",
        ]

        seen: set[str] = set()
        for key in profile_keys:
            if not key or key in seen:
                continue
            seen.add(str(key))
            profile = profiles.get(str(key))
            targets = self._targets_from_backtest_profile(profile)
            if targets is not None:
                return targets
        return None

    def _targets_from_backtest_profile(self, profile: Any) -> Optional[dict[str, dict[str, float]]]:
        if not isinstance(profile, dict):
            return None
        horizons = profile.get("horizons")
        if not isinstance(horizons, dict):
            return None

        targets: dict[str, dict[str, float]] = {}
        has_value = False
        for period in DEFAULT_TARGETS:
            horizon = horizons.get(period)
            mfe = horizon.get("mfe") if isinstance(horizon, dict) else None
            if not isinstance(mfe, dict):
                continue
            targets[period] = {}
            for quantile in ("p50", "p75", "p90"):
                value = self._to_float(mfe.get(quantile))
                if value is not None:
                    targets[period][quantile] = value
                    has_value = True
        return targets if has_value else None

    @staticmethod
    def _normalize_targets(raw: dict[str, Any]) -> dict[str, dict[str, float]]:
        normalized: dict[str, dict[str, float]] = {}
        for period, values in DEFAULT_TARGETS.items():
            source = raw.get(period, values) if isinstance(raw, dict) else values
            if not isinstance(source, dict):
                source = {}
            normalized[period] = {
                quantile: ExitPlanService._target_float(source.get(quantile), values[quantile])
                for quantile in ("p50", "p75", "p90")
            }
        return normalized

    @staticmethod
    def _target_float(value: Any, default: float) -> float:
        try:
            parsed = float(value)
            if pd.isna(parsed):
                return default
            return parsed
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
        return round(value, digits) if value is not None else None

    def load_history_frame(
        self,
        db: Session,
        code: str,
        *,
        end_date: Optional[date] = None,
        days: int = 260,
    ) -> pd.DataFrame:
        query = db.query(StockDaily).filter(StockDaily.code == str(code).zfill(6))
        if end_date is not None:
            query = query.filter(StockDaily.trade_date <= end_date)
        rows = query.order_by(StockDaily.trade_date.desc(), StockDaily.id.desc()).limit(days).all()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "date": row.trade_date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                }
                for row in reversed(rows)
            ]
        )

    def build_exit_plan(
        self,
        *,
        code: str,
        history_df: pd.DataFrame,
        entry_price: Optional[float],
        current_price: Optional[float] = None,
        entry_date: Optional[date] = None,
        verdict: Optional[str] = None,
        signal_type: Optional[str] = None,
        is_intraday: bool = False,
    ) -> dict[str, Any]:
        frame = self._prepare_frame(history_df)
        latest = frame.iloc[-1] if not frame.empty else {}
        current = self._to_float(current_price) or self._to_float(getattr(latest, "get", lambda _k: None)("close"))
        entry = self._to_float(entry_price)
        basis = entry or current

        target_prices = self._build_target_prices(basis)
        if frame.empty:
            return self._empty_plan(entry, current, target_prices, "行情不足，暂按谨慎持有处理。")

        entry_frame = self._entry_frame(frame, entry_date)
        metrics = self._build_metrics(frame, entry_frame, entry, exclude_latest_for_structure=is_intraday)
        pnl = (current / entry - 1.0) if entry and current else None
        target_progress = self._target_progress(pnl)
        morning_state, afternoon_action, key_levels = self._intraday_state(
            frame=frame,
            current=current,
            metrics=metrics,
            verdict=verdict,
            signal_type=signal_type,
            is_intraday=is_intraday,
        )
        action, phase, reason, rules = self._decide_action(
            current=current,
            entry=entry,
            pnl=pnl,
            target_progress=target_progress,
            metrics=metrics,
            verdict=verdict,
            signal_type=signal_type,
            is_intraday=is_intraday,
            morning_state=morning_state,
        )

        return {
            "action": action,
            "action_label": ACTION_LABELS[action],
            "phase": phase,
            "entry_price": self._round(entry),
            "current_price": self._round(current),
            "pnl": self._round(pnl),
            "mfe_since_entry": self._round(metrics["mfe_since_entry"]),
            "mae_since_entry": self._round(metrics["mae_since_entry"]),
            "drawdown_from_mfe": self._round(metrics["drawdown_from_mfe"]),
            "target_progress": target_progress,
            "target_prices": target_prices,
            "risk_lines": {
                "structure_line": self._round(metrics["structure_line"]),
                "hard_stop": self._round(metrics["hard_stop"]),
                "trailing_stop": self._round(metrics["trailing_stop"]),
                "ema20": self._round(metrics["ema20"]),
                "signal_low": self._round(metrics["signal_low"]),
                "recent_low": self._round(metrics["recent_low"]),
                "atr14": self._round(metrics["atr14"]),
            },
            "morning_state": morning_state,
            "afternoon_action": afternoon_action,
            "key_levels": key_levels,
            "reason": reason,
            "rules": rules,
        }

    def _prepare_frame(self, history_df: pd.DataFrame) -> pd.DataFrame:
        if history_df is None or history_df.empty:
            return pd.DataFrame()
        frame = history_df.copy()
        if "trade_date" in frame.columns and "date" not in frame.columns:
            frame = frame.rename(columns={"trade_date": "date"})
        for col in ["open", "high", "low", "close", "volume"]:
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date", "high", "low", "close"])
        return frame.sort_values("date").reset_index(drop=True)

    def _entry_frame(self, frame: pd.DataFrame, entry_date: Optional[date]) -> pd.DataFrame:
        if frame.empty:
            return frame
        if entry_date is None:
            return frame
        entry_ts = pd.Timestamp(entry_date)
        sliced = frame[frame["date"] >= entry_ts].copy()
        return sliced if not sliced.empty else frame.tail(1).copy()

    def _build_target_prices(self, basis: Optional[float]) -> dict[str, dict[str, Optional[float]]]:
        prices: dict[str, dict[str, Optional[float]]] = {}
        for period, values in self.targets.items():
            prices[period] = {
                quantile: self._round(basis * (1.0 + pct)) if basis else None
                for quantile, pct in values.items()
            }
        return prices

    def _target_progress(self, pnl: Optional[float]) -> str:
        if pnl is None:
            return "unknown"
        ten_day = self.targets["10d"]
        if pnl >= ten_day["p90"]:
            return "p90"
        if pnl >= ten_day["p75"]:
            return "p75"
        if pnl >= ten_day["p50"]:
            return "p50"
        return "below_p50"

    def _build_metrics(
        self,
        frame: pd.DataFrame,
        entry_frame: pd.DataFrame,
        entry: Optional[float],
        *,
        exclude_latest_for_structure: bool = False,
    ) -> dict[str, Optional[float]]:
        risk_cfg = self.config.get("risk") or {}
        atr_period = int(risk_cfg.get("atr_period", 14))
        ema_period = int(risk_cfg.get("ema_period", 20))
        recent_low_lookback = int(risk_cfg.get("recent_low_lookback", 5))
        hard_stop_pct = float(risk_cfg.get("hard_stop_pct", 0.08))

        close = frame["close"]
        high = frame["high"]
        low = frame["low"]
        prev_close = close.shift(1)
        true_range = pd.concat(
            [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr14 = self._to_float(true_range.rolling(atr_period, min_periods=1).mean().iloc[-1])
        ema20 = self._to_float(close.ewm(span=ema_period, adjust=False).mean().iloc[-1])
        structure_frame = frame.iloc[:-1] if exclude_latest_for_structure and len(frame) > 1 else frame
        recent_low = self._to_float(structure_frame.tail(recent_low_lookback)["low"].min())
        signal_low = self._to_float(entry_frame.iloc[0]["low"]) if not entry_frame.empty else None
        latest_close = self._to_float(frame.iloc[-1]["close"])

        structural_candidates = [v for v in [recent_low, signal_low] if v is not None]
        if ema20 is not None and latest_close is not None and latest_close >= ema20:
            structural_candidates.append(ema20)
        structure_line = max(structural_candidates) if structural_candidates else None
        hard_stop = None
        if entry is not None:
            hard_stop = entry * (1.0 - hard_stop_pct)
            if structure_line is not None:
                hard_stop = min(hard_stop, structure_line)
        elif structure_line is not None and atr14 is not None:
            hard_stop = structure_line - atr14

        highest = self._to_float(entry_frame["high"].max()) if not entry_frame.empty else None
        lowest = self._to_float(entry_frame["low"].min()) if not entry_frame.empty else None
        mfe = (highest / entry - 1.0) if highest is not None and entry else None
        mae = (lowest / entry - 1.0) if lowest is not None and entry else None
        drawdown = (latest_close / highest - 1.0) if latest_close is not None and highest else None
        drawdown_limit = float(
            risk_cfg.get(
                "protect_trailing_drawdown" if mfe is not None and mfe >= self.targets["10d"]["p75"] else "initial_trailing_drawdown",
                0.08,
            )
        )
        trailing_stop = highest * (1.0 - drawdown_limit) if highest is not None else None
        if structure_line is not None and trailing_stop is not None:
            trailing_stop = max(structure_line, trailing_stop)

        return {
            "atr14": atr14,
            "ema20": ema20,
            "recent_low": recent_low,
            "signal_low": signal_low,
            "structure_line": structure_line,
            "hard_stop": hard_stop,
            "trailing_stop": trailing_stop,
            "mfe_since_entry": mfe,
            "mae_since_entry": mae,
            "drawdown_from_mfe": drawdown,
        }

    def _intraday_state(
        self,
        *,
        frame: pd.DataFrame,
        current: Optional[float],
        metrics: dict[str, Optional[float]],
        verdict: Optional[str],
        signal_type: Optional[str],
        is_intraday: bool,
    ) -> tuple[Optional[str], Optional[str], dict[str, Optional[float]]]:
        if not is_intraday:
            return None, None, {"morning_low": None, "morning_high": None, "reclaim_line": None}

        last = frame.iloc[-1]
        morning_low = self._to_float(last.get("low"))
        morning_high = self._to_float(last.get("high"))
        open_price = self._to_float(last.get("open"))
        structure_line = metrics["structure_line"]
        reclaim_line = structure_line
        key_levels = {
            "morning_low": self._round(morning_low),
            "morning_high": self._round(morning_high),
            "reclaim_line": self._round(reclaim_line),
        }

        if structure_line is not None and morning_low is not None and current is not None:
            if morning_low < structure_line <= current:
                return "wash_observe", "hold_if_reclaim", key_levels
            if current < structure_line:
                return "breakdown_risk", "exit", key_levels

        volume = self._to_float(last.get("volume"))
        avg20_volume = self._to_float(frame.iloc[:-1].tail(20)["volume"].mean()) if len(frame) > 1 and "volume" in frame.columns else None
        vol_ratio = volume / avg20_volume if volume is not None and avg20_volume not in (None, 0) else None
        high_drop = (current / morning_high - 1.0) if current is not None and morning_high else None
        risk_cfg = self.config.get("risk") or {}
        if (
            signal_type == "distribution_risk"
            or verdict == "FAIL"
            or (
                open_price is not None
                and current is not None
                and current < open_price
                and vol_ratio is not None
                and vol_ratio >= float(risk_cfg.get("distribution_volume_ratio", 1.5))
                and high_drop is not None
                and high_drop <= -float(risk_cfg.get("distribution_intraday_drop", 0.03))
            )
        ):
            return "distribution_risk", "trim", key_levels
        if open_price is not None and current is not None and morning_high is not None and current >= open_price and current >= morning_high * 0.98:
            return "strong_push", "hold", key_levels
        return "normal_pullback", "trim_if_break_low", key_levels

    def _decide_action(
        self,
        *,
        current: Optional[float],
        entry: Optional[float],
        pnl: Optional[float],
        target_progress: str,
        metrics: dict[str, Optional[float]],
        verdict: Optional[str],
        signal_type: Optional[str],
        is_intraday: bool,
        morning_state: Optional[str],
    ) -> tuple[str, str, str, list[str]]:
        rules: list[str] = []
        structure_line = metrics["structure_line"]
        hard_stop = metrics["hard_stop"]
        trailing_stop = metrics["trailing_stop"]

        if entry is None:
            rules.append("no_entry_price")
            return "hold_cautious", "initial", "未设置入场价，仅给出目标区间与结构线，按谨慎持有处理。", rules

        if morning_state == "wash_observe":
            rules.append("intraday_reclaim_structure")
            return "wash_observe", "risk_control", "盘中刺破结构线后收回，下午观察能否站稳收复线。", rules

        if current is not None and hard_stop is not None and current < hard_stop:
            rules.append("hard_stop_broken")
            return "exit", "risk_control", "跌破硬止损线，退出优先。", rules

        if verdict == "FAIL":
            rules.append("verdict_fail")
            if is_intraday and current is not None and structure_line is not None and current >= structure_line:
                return "trim", "risk_control", "量价复核转 FAIL，但中盘未有效跌破结构，先减仓。", rules
            return "exit", "risk_control", "量价复核转 FAIL，执行退出。", rules

        if signal_type == "distribution_risk" or morning_state == "distribution_risk":
            rules.append("distribution_risk")
            return "trim", "risk_control", "出现派发风险，先减仓锁定主动权。", rules

        if current is not None and trailing_stop is not None and current < trailing_stop and (pnl or 0) > 0:
            rules.append("trailing_stop_broken")
            return "trim", "trend_trailing", "跌破移动止盈线，减仓保护利润。", rules

        if current is not None and structure_line is not None and current < structure_line and not is_intraday:
            rules.append("structure_line_broken")
            return "exit", "risk_control", "收盘跌破结构止损线，退出观察。", rules

        if target_progress in {"p75", "p90"}:
            rules.append(f"target_{target_progress}_reached")
            return "take_profit_partial", "profit_protect", "收益达到 MFE 高分位目标，适合部分止盈并用移动止盈保护剩余仓位。", rules

        if target_progress == "p50":
            rules.append("target_p50_reached")
            return "hold", "expansion", "收益进入 MFE 中位目标，继续持有并观察 P75。", rules

        if pnl is not None and pnl < 0:
            rules.append("below_entry")
            return "hold_cautious", "initial", "仍在入场价下方，控制仓位并盯结构线。", rules

        rules.append("trend_intact")
        return "hold", "expansion", "价格仍在结构线上方，继续持有。", rules

    def _empty_plan(
        self,
        entry: Optional[float],
        current: Optional[float],
        target_prices: dict[str, dict[str, Optional[float]]],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "action": "hold_cautious",
            "action_label": ACTION_LABELS["hold_cautious"],
            "phase": "initial",
            "entry_price": self._round(entry),
            "current_price": self._round(current),
            "pnl": self._round((current / entry - 1.0) if current and entry else None),
            "mfe_since_entry": None,
            "mae_since_entry": None,
            "drawdown_from_mfe": None,
            "target_progress": "unknown",
            "target_prices": target_prices,
            "risk_lines": {
                "structure_line": None,
                "hard_stop": None,
                "trailing_stop": None,
                "ema20": None,
                "signal_low": None,
                "recent_low": None,
                "atr14": None,
            },
            "morning_state": None,
            "afternoon_action": None,
            "key_levels": {"morning_low": None, "morning_high": None, "reclaim_line": None},
            "reason": reason,
            "rules": ["insufficient_history"],
        }
