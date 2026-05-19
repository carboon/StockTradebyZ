#!/usr/bin/env python3
"""
newB1明日之星检测工具
===================

用法:
  # 检测单个日期
  python detect_tomorrow_stars.py --date 2026-05-08

  # 检测多个日期
  python detect_tomorrow_stars.py --date 2026-05-08 2026-05-06

  # 检测最近5个交易日
  python detect_tomorrow_stars.py --recent 5

  # 检测所有可用日期
  python detect_tomorrow_stars.py --all

  # 只显示明日之星
  python detect_tomorrow_stars.py --date 2026-05-08 --stars-only

  # 输出JSON文件
  python detect_tomorrow_stars.py --date 2026-05-08 --output result.json
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "pipeline"))
sys.path.insert(0, str(_ROOT / "agent"))

from quant_reviewer import (
    prepare_review_frame,
    review_prepared_frame,
    load_config as load_reviewer_config,
    DEFAULT_CONFIG,
)


def get_available_dates() -> list[str]:
    """获取所有可用的newB1输出日期"""
    output_dir = _ROOT / "newB1" / "output"
    dates = []
    for f in output_dir.glob("new_b1_*.json"):
        name = f.stem.replace("new_b1_", "")
        if name != "latest":
            dates.append(name)
    return sorted(dates, reverse=True)


def load_new_b1_candidates(date: str) -> list[dict]:
    """加载指定日期的newB1候选股票"""
    json_path = _ROOT / "newB1" / "output" / f"new_b1_{date}.json"
    if not json_path.exists():
        return []
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("candidates", [])


def load_stock_data(code: str) -> pd.DataFrame | None:
    """加载股票日线数据"""
    csv_path = _ROOT / "data" / "raw" / f"{code}.csv"
    if not csv_path.exists():
        return None
    return pd.read_csv(csv_path)


def is_tomorrow_star(result: dict) -> bool:
    """判断是否为明日之星"""
    verdict = result.get("verdict")
    signal_type = result.get("signal_type")
    total_score = result.get("total_score", 0)
    return (
        verdict == "PASS"
        and signal_type == "trend_start"
        and total_score >= 4.0
    )


def analyze_date(date: str, config: dict) -> dict:
    """分析指定日期的newB1候选股票"""
    candidates = load_new_b1_candidates(date)
    if not candidates:
        return {
            "date": date,
            "candidates_count": 0,
            "tomorrow_stars": [],
            "top_others": [],
        }

    tomorrow_stars = []
    others = []

    for cand in candidates:
        code = cand["code"]
        name = cand["name"]
        signal_type = cand.get("signal_type", "N/A")

        df = load_stock_data(code)
        if df is None:
            continue

        try:
            frame = prepare_review_frame(df, config)
            result = review_prepared_frame(
                frame, config, code=code, asof_date=date, strategy="new_b1"
            )

            stock_info = {
                "code": code,
                "name": name,
                "b1_signal": signal_type,
                "total_score": result.get("total_score", 0),
                "trend_score": result.get("scores", {}).get("trend_structure", 0),
                "position_score": result.get("scores", {}).get("price_position", 0),
                "volume_score": result.get("scores", {}).get("volume_behavior", 0),
                "abnormal_score": result.get("scores", {}).get("previous_abnormal_move", 0),
                "signal_type": result.get("signal_type"),
                "verdict": result.get("verdict"),
            }

            if is_tomorrow_star(result):
                tomorrow_stars.append(stock_info)
            else:
                others.append(stock_info)

        except Exception:
            continue

    others.sort(key=lambda x: x["total_score"], reverse=True)

    return {
        "date": date,
        "candidates_count": len(candidates),
        "tomorrow_stars": tomorrow_stars,
        "top_others": others[:5],
    }


def print_single_result(result: dict, stars_only: bool = False) -> None:
    """打印单日结果"""
    date = result["date"]
    stars = result["tomorrow_stars"]
    candidates_count = result["candidates_count"]

    print(f"\n{'='*80}")
    print(f"📅 日期: {date} | newB1候选: {candidates_count}只")
    print(f"{'='*80}")

    print(f"\n🌟 明日之星 (PASS + trend_start + score>=4.0): {len(stars)}只")
    if stars:
        print(f"{'代码':<8} {'名称':<10} {'B1信号':<14} {'总分':<5} {'趋势':<5} {'位置':<5} {'量价':<5} {'异动':<5}")
        print("-" * 75)
        for s in stars:
            print(f"{s['code']:<8} {s['name']:<10} {s['b1_signal']:<14} "
                  f"{s['total_score']:<5.1f} {s['trend_score']:<5} {s['position_score']:<5} "
                  f"{s['volume_score']:<5} {s['abnormal_score']:<5}")
    else:
        print("  无")

    if not stars_only:
        others = result["top_others"]
        print(f"\n📊 Top 5 非明日之星 (按质量分排序)")
        if others:
            print(f"{'代码':<8} {'名称':<10} {'B1信号':<14} {'总分':<5} {'趋势':<5} {'位置':<5} {'量价':<5} {'异动':<5} {'判定':<8}")
            print("-" * 85)
            for s in others:
                print(f"{s['code']:<8} {s['name']:<10} {s['b1_signal']:<14} "
                      f"{s['total_score']:<5.1f} {s['trend_score']:<5} {s['position_score']:<5} "
                      f"{s['volume_score']:<5} {s['abnormal_score']:<5} {s['verdict']:<8}")
        else:
            print("  无")


def print_summary(results: list[dict]) -> None:
    """打印汇总"""
    total_stars = sum(len(r["tomorrow_stars"]) for r in results)
    print(f"\n{'='*80}")
    print("📋 汇总统计")
    print(f"{'='*80}")
    print(f"分析日期数: {len(results)}")
    print(f"明日之星总数: {total_stars}只")
    print("\n按日期分布:")
    for r in results:
        print(f"  {r['date']}: {len(r['tomorrow_stars'])}只")
    print(f"{'='*80}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="newB1明日之星检测工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  python detect_tomorrow_stars.py --date 2026-05-08
  python detect_tomorrow_stars.py --date 2026-05-08 2026-05-06
  python detect_tomorrow_stars.py --recent 5
  python detect_tomorrow_stars.py --all
  python detect_tomorrow_stars.py --date 2026-05-08 --stars-only
        """,
    )
    parser.add_argument("--date", "-d", nargs="+", help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--recent", "-r", type=int, help="最近N个交易日")
    parser.add_argument("--all", "-a", action="store_true", help="分析所有可用日期")
    parser.add_argument("--stars-only", "-s", action="store_true", help="只显示明日之星")
    parser.add_argument("--output", "-o", help="输出JSON文件路径")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有可用日期")

    args = parser.parse_args()

    # 加载配置
    config_path = _ROOT / "config" / "quant_review.yaml"
    config = load_reviewer_config(config_path) if config_path.exists() else DEFAULT_CONFIG.copy()

    # 列出可用日期
    available_dates = get_available_dates()
    if args.list:
        print("可用的日期:")
        for d in available_dates:
            json_path = _ROOT / "newB1" / "output" / f"new_b1_{d}.json"
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
                count = len(data.get("candidates", []))
            print(f"  {d}: {count}只候选")
        return

    # 确定要分析的日期
    dates = []
    if args.date:
        dates = args.date
    elif args.recent:
        dates = available_dates[:args.recent]
    elif args.all:
        dates = available_dates
    else:
        # 默认分析最近一个日期
        dates = available_dates[:1] if available_dates else []
        if not dates:
            print("错误: 没有可用的newB1输出文件")
            return

    # 执行分析
    results = []
    for date in dates:
        result = analyze_date(date, config)
        results.append(result)
        print_single_result(result, stars_only=args.stars_only)

    # 打印汇总
    if len(results) > 1:
        print_summary(results)

    # 保存结果
    if args.output:
        output_path = Path(args.output)
    elif len(dates) > 1:
        output_path = _ROOT / "newB1" / "output" / "tomorrow_stars_analysis.json"
    else:
        output_path = None

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_path}")


if __name__ == "__main__":
    main()
