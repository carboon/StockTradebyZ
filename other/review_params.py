from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ReviewRuleParams:
    pass_score_min: float = 4.0
    watch_score_min: float = 3.2
    volume_fail_max: float = 1.5
    trend_start_min_trend: float = 3.6
    trend_start_min_position: float = 3.4
    trend_start_min_volume: float = 3.4
    trend_start_max_range_position: float = 0.88
    high_position_risk: float = 0.88
    overheat_bias_pct: float = 12.0
    multi_limit_high_position: float = 0.82
    multi_limit_bias_pct: float = 10.0
    destructive_volume_ratio: float = 1.8
    turnover_f_good_low: float = 2.0
    turnover_f_good_high: float = 12.0
    turnover_f_hot: float = 25.0
    turnover_f_cold: float = 0.5
    tushare_volume_good_low: float = 1.2
    tushare_volume_good_high: float = 3.5
    tushare_volume_hot: float = 6.0
    main_net_confirm_pct: float = 0.8
    main_net_outflow_pct: float = -0.8
    abnormal_main_net_confirm_pct: float = 1.0
    abnormal_main_net_outflow_pct: float = -1.0
    abnormal_gain_min: float = 2.5
    abnormal_gain_strong: float = 6.0
    abnormal_gain_medium: float = 3.0
    abnormal_volume_ratio_min: float = 1.3
    abnormal_volume_ratio_strong: float = 2.0
    abnormal_volume_ratio_medium: float = 1.5
    abnormal_follow_through_hot: float = 80.0
    abnormal_follow_through_ok_max: float = 50.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def load_review_rule_params(path: str | Path | None = None) -> ReviewRuleParams:
    if not path:
        return ReviewRuleParams()
    p = Path(path)
    if not p.exists():
        return ReviewRuleParams()

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if "review_thresholds" in raw:
        raw = raw["review_thresholds"] or {}
    allowed = {f.name for f in fields(ReviewRuleParams)}
    values: dict[str, Any] = {}
    for key, value in raw.items():
        if key in allowed and value is not None:
            values[key] = float(value)
    return ReviewRuleParams(**values)
