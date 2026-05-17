"""
code_review.py
~~~~~~~~~~~~~~
确定性代码化复评入口。

本入口不调用 Gemini、OpenAI-compatible、Codex CLI 或任何图像理解模型。

用法：
    python agent/code_review.py
    python agent/code_review.py --config config/code_review.yaml

输出：
    ./data/review/{pick_date}/{code}.json
    ./data/review/{pick_date}/suggestion.json
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import yaml

try:
    from base_reviewer import BaseReviewer
except ImportError:
    from agent.base_reviewer import BaseReviewer


_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _ROOT / "config" / "code_review.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "candidates": "data/candidates/candidates_latest.json",
    "raw_dir": "data/raw",
    "output_dir": "data/review",
    "prompt_path": "agent/prompt.md",
    "request_delay": 0,
    "skip_existing": False,
    "suggest_min_score": 4.0,
    "suggest_top_n": 10,
    "review_min_bars": 120,
    "tushare_start": "20190101",
    "tushare_overlap_days": 5,
    "use_tushare_review_data": True,
    "review_data_dir": "data/tushare_review",
    "review_thresholds_path": "config/review_thresholds.yaml",
    "filters": {
        "enabled": True,
        "exclude_st": True,
        "min_listing_days": 120,
        "exclude_suspended": True,
        "min_avg_amount_20d": 20000000,
        "min_industry_rank_pct": 0.25,
        "market_regime_min": 0.35,
    },
}


def _resolve_cfg_path(path_like: str | Path, base_dir: Path = _ROOT) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else (base_dir / p)


def load_local_env(env_path: Path | None = None) -> None:
    """从项目根目录 .env 加载环境变量；已存在的环境变量不覆盖。"""
    path = env_path or (_ROOT / ".env")
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    cfg_path = config_path or _DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = {**DEFAULT_CONFIG, **raw}

    cfg["candidates"] = _resolve_cfg_path(cfg["candidates"])
    cfg["raw_dir"] = _resolve_cfg_path(cfg["raw_dir"])
    cfg["output_dir"] = _resolve_cfg_path(cfg["output_dir"])
    cfg["prompt_path"] = _resolve_cfg_path(cfg["prompt_path"])
    cfg["review_data_dir"] = _resolve_cfg_path(cfg["review_data_dir"])
    cfg["review_thresholds_path"] = _resolve_cfg_path(cfg["review_thresholds_path"])

    return cfg


class CodeReviewRunner(BaseReviewer):
    """BaseReviewer builds all review fields in deterministic code."""

    def review_stock(self, code: str, prompt: str, scorecard: dict[str, Any]) -> dict[str, Any]:
        return scorecard


def main() -> None:
    parser = argparse.ArgumentParser(description="确定性代码化图表复评")
    parser.add_argument(
        "--config",
        default=str(_DEFAULT_CONFIG_PATH),
        help="配置文件路径（默认 config/code_review.yaml）",
    )
    args = parser.parse_args()

    load_local_env()
    config = load_config(Path(args.config))
    reviewer = CodeReviewRunner(config)
    reviewer.run()


if __name__ == "__main__":
    main()
