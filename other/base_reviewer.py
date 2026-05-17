"""
base_reviewer.py
~~~~~~~~~~~~~~~~
提供代码化复评的基础架构：
- 加载配置和 prompt
- 读取候选股票列表
- 遍历候选并生成确定性复评结果
- 结果汇总和输出
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

try:
    from review_scorecard import ReviewScorecardBuilder
    from review_params import load_review_rule_params
except ImportError:
    from agent.review_scorecard import ReviewScorecardBuilder
    from agent.review_params import load_review_rule_params

try:
    from pipeline.market_context import MarketContextBuilder, filter_config_from_dict
except ImportError:
    MarketContextBuilder = None
    filter_config_from_dict = None
try:
    from pipeline.db import import_review_results
except Exception:
    import_review_results = None


class BaseReviewer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.prompt = self.load_prompt(Path(config["prompt_path"]))
        self.output_dir = Path(config["output_dir"])
        self.rule_params = load_review_rule_params(config.get("review_thresholds_path"))
        self.scorecard_builder = ReviewScorecardBuilder(
            config.get("raw_dir", "data/raw"),
            min_bars=int(config.get("review_min_bars", 120)),
            tushare_start=str(config.get("tushare_start", "20190101")),
            overlap_days=int(config.get("tushare_overlap_days", 5)),
            review_data_dir=config.get("review_data_dir"),
            use_tushare_review_data=bool(config.get("use_tushare_review_data", True)),
            rule_params=self.rule_params,
            db_path=config.get("db_path"),
        )
        self.market_context = None
        if config.get("filters", {}).get("enabled", False):
            if MarketContextBuilder is None or filter_config_from_dict is None:
                raise RuntimeError("启用复评过滤需要 pipeline.market_context 模块。")
            self.market_context = MarketContextBuilder(
                config.get("raw_dir", "data/raw"),
                config=filter_config_from_dict(config.get("filters")),
            )

    @staticmethod
    def load_prompt(prompt_path: Path) -> str:
        return prompt_path.read_text(encoding="utf-8")

    @staticmethod
    def load_candidates(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def review_stock(self, code: str, prompt: str, scorecard: dict) -> dict:
        """子类可覆写此方法；默认 runner 直接返回代码评分卡。"""
        raise NotImplementedError("子类必须实现 review_stock 方法")

    def build_scorecard(self, pick_date: str, candidate: dict) -> dict:
        if self.market_context is not None:
            eligibility = self.market_context.evaluate(str(candidate["code"]), pick_date)
            if eligibility.blocked:
                return self._blocked_scorecard(str(candidate["code"]), pick_date, candidate, eligibility)

        return self.scorecard_builder.build(
            code=str(candidate["code"]),
            pick_date=pick_date,
            candidate=candidate,
        )

    def _blocked_scorecard(self, code: str, pick_date: str, candidate: dict, eligibility) -> dict:
        evidence = {
            "strategy": candidate.get("strategy", ""),
            "candidate_close": candidate.get("close", 0),
            "filter_status": eligibility.status,
            "filter_reasons": eligibility.reasons,
            **eligibility.evidence,
        }
        comment = f"过滤未通过：{','.join(eligibility.reasons)}，不进入复评排序。"
        return {
            "code": code,
            "date": pick_date,
            "weights": {},
            "review_thresholds": self.rule_params.to_dict(),
            "scores": {
                "trend_structure": 1.0,
                "price_position": 1.0,
                "volume_behavior": 1.0,
                "previous_abnormal_move": 1.0,
            },
            "evidence": evidence,
            "code_total_score": 1.0,
            "total_score": 1.0,
            "signal_type": "distribution_risk",
            "verdict": "FAIL",
            "trend_reasoning": "个股资格或市场过滤未通过，趋势结构不进入正常评分。",
            "position_reasoning": "过滤未通过时不评估价格位置。",
            "volume_reasoning": "过滤未通过时不评估量价结构。",
            "abnormal_move_reasoning": "过滤未通过时不评估前期异动。",
            "signal_reasoning": "复评前置过滤触发硬排除，兼容输出失败结论。",
            "visual_check": "conflict",
            "filter_status": eligibility.status,
            "filter_reasons": eligibility.reasons,
            "comment": comment,
            "ai_adjustment": 0.0,
            "final_score_source": "code_scorecard",
        }

    def generate_suggestion(
        self,
        pick_date: str,
        all_results: List[dict],
        min_score: float,
        top_n: int,
    ) -> dict:
        ranked = sorted(all_results, key=lambda r: r.get("total_score", 0), reverse=True)
        top_results = ranked[:top_n]
        excluded = [r["code"] for r in ranked[top_n:]]

        above_threshold = [
            r["code"]
            for r in ranked
            if r.get("total_score", 0) >= min_score
        ]

        recommendations = [
            {
                "rank": i + 1,
                "code": r["code"],
                "verdict": r.get("verdict", ""),
                "total_score": r.get("total_score", 0),
                "signal_type": r.get("signal_type", ""),
                "comment": r.get("comment", ""),
                "meets_min_score": r.get("total_score", 0) >= min_score,
            }
            for i, r in enumerate(top_results)
        ]

        return {
            "date": pick_date,
            "min_score_threshold": min_score,
            "recommendation_top_n": top_n,
            "total_reviewed": len(all_results),
            "above_threshold": above_threshold,
            "recommendations": recommendations,
            "excluded": excluded,
        }

    def run(self):
        candidates_data = self.load_candidates(Path(self.config["candidates"]))
        pick_date: str = candidates_data["pick_date"]
        candidates: List[dict] = candidates_data["candidates"]
        print(f"[INFO] pick_date={pick_date}，候选股票数={len(candidates)}")
        print("[INFO] 使用确定性代码复评全部候选，汇总时按评分取 Top N。")

        out_dir = self.output_dir / pick_date
        out_dir.mkdir(parents=True, exist_ok=True)

        all_results: List[dict] = []
        failed_codes: List[str] = []

        for i, candidate in enumerate(candidates, 1):
            code: str = candidate["code"]
            out_file = out_dir / f"{code}.json"

            if self.config.get("skip_existing", False) and out_file.exists():
                print(f"[{i}/{len(candidates)}] {code} — 已存在，跳过。")
                with open(out_file, encoding="utf-8") as f:
                    result = json.load(f)
                all_results.append(result)
                continue

            print(f"[{i}/{len(candidates)}] {code} — 正在代码复评 ...", end=" ", flush=True)

            try:
                scorecard = self.build_scorecard(pick_date, candidate)
                result = self.review_stock(
                    code=code,
                    prompt=self.prompt,
                    scorecard=scorecard,
                )
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                all_results.append(result)
                verdict = result.get("verdict", "?")
                score = result.get("total_score", "?")
                print(f"完成 — verdict={verdict}, score={score}")
            except Exception as e:
                print(f"失败 — {e}")
                failed_codes.append(code)

            if i < len(candidates):
                time.sleep(self.config.get("request_delay", 5))

        print(f"\n[INFO] 评分完成：成功 {len(all_results)} 支，失败/跳过 {len(failed_codes)} 支")
        if failed_codes:
            print(f"[WARN] 未处理股票：{failed_codes}")

        if not all_results:
            print("[ERROR] 没有可用的评分结果，跳过汇总。")
            sys.exit(1)

        print("\n[INFO] 正在生成汇总推荐建议 ...")
        min_score = self.config.get("suggest_min_score", 4.0)
        top_n = int(self.config.get("suggest_top_n", 10))
        suggestion = self.generate_suggestion(
            pick_date=pick_date,
            all_results=all_results,
            min_score=min_score,
            top_n=top_n,
        )
        suggestion_file = out_dir / "suggestion.json"
        with open(suggestion_file, "w", encoding="utf-8") as f:
            json.dump(suggestion, f, ensure_ascii=False, indent=2)
        if import_review_results is not None:
            try:
                import_review_results(self.output_dir, self.config.get("db_path"))
            except Exception as exc:
                print(f"[WARN] 复评结果同步 DuckDB 失败，保留 JSON 输出：{exc}")
        print(f"[INFO] 汇总推荐已写入: {suggestion_file}")
        print(f"       推荐股票数（按 score Top {top_n}）: {len(suggestion['recommendations'])}")
        print(f"       达到门槛（score≥{min_score}）: {len(suggestion['above_threshold'])}")

        print("\n✅ 全部完成。")
        print(f"   输出目录: {out_dir}")
