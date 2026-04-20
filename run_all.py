"""
run_all.py
~~~~~~~~~~
一键运行完整交易选股流程：

  步骤 1  pipeline/fetch_kline.py   — 拉取最新 K 线数据
  步骤 2  pipeline/cli.py preselect — 量化初选，生成候选列表
  步骤 3  dashboard/export_kline_charts.py — 导出候选股 K 线图
  步骤 4  agent/*_review.py         — LLM 图表分析评分
  步骤 5  打印推荐购买的股票

用法：
    python run_all.py                           # 使用 quant 程序化复核（默认）
    python run_all.py --reviewer quant          # 使用量化评分（默认）
    python run_all.py --reviewer glm            # 使用智谱 GLM-4V-Flash（免费）
    python run_all.py --reviewer qwen           # 使用通义千问 VL
    python run_all.py --reviewer gemini         # 使用 Google Gemini
    python run_all.py --skip-fetch              # 跳过行情下载（已有历史数据时）
    python run_all.py --start-from 3            # 从第 3 步开始（跳过前两步）
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable  # 与当前进程同一个 Python 解释器
MIN_PYTHON = (3, 11)

# 支持的 reviewer 配置
REVIEWERS = {
    "glm": {
        "name": "GLM-4V-Flash",
        "script": ROOT / "agent" / "glm_reviewer.py",
        "config": ROOT / "config" / "glm_review.yaml",
        "env_var": "ZHIPUAI_API_KEY",
        "free": True,
    },
    "qwen": {
        "name": "通义千问 VL",
        "script": ROOT / "agent" / "qwen_reviewer.py",
        "config": ROOT / "config" / "qwen_review.yaml",
        "env_var": "DASHSCOPE_API_KEY",
        "free": False,
    },
    "gemini": {
        "name": "Gemini",
        "script": ROOT / "agent" / "gemini_review.py",
        "config": ROOT / "config" / "gemini_review.yaml",
        "env_var": "GEMINI_API_KEY",
        "free": False,
    },
    "quant": {
        "name": "量化评分",
        "script": ROOT / "agent" / "quant_reviewer.py",
        "config": ROOT / "config" / "quant_review.yaml",
        "env_var": None,
        "free": True,
    },
}


def _detect_board(ts_code: str, symbol: str) -> str:
    ts_code = str(ts_code).upper()
    symbol = str(symbol).zfill(6)
    if ts_code.endswith(".BJ") or symbol.startswith(("4", "8")):
        return "bj"
    if ts_code.endswith(".SZ") and symbol.startswith(("300", "301")):
        return "gem"
    if ts_code.endswith(".SH") and symbol.startswith("688"):
        return "star"
    return "main"


def _load_expected_fetch_codes() -> set[str]:
    """按当前 fetch 配置推导第 1 步应抓取的全部股票代码。"""
    cfg_path = ROOT / "config" / "fetch_kline.yaml"
    if not cfg_path.exists():
        return set()

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    stocklist_path = Path(cfg.get("stocklist", "./pipeline/stocklist.csv"))
    if not stocklist_path.is_absolute():
        stocklist_path = ROOT / stocklist_path
    if not stocklist_path.exists():
        return set()

    exclude_boards = {str(x).lower() for x in (cfg.get("exclude_boards") or [])}
    codes: set[str] = set()
    with open(stocklist_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = str(row.get("symbol", "")).zfill(6)
            if not symbol or symbol == "000000":
                continue
            board = _detect_board(row.get("ts_code", ""), symbol)
            if board in exclude_boards:
                continue
            codes.add(symbol)
    return codes


def _has_all_expected_data(raw_dir: Path, expected_codes: set[str] | None = None) -> bool:
    """检查 data/raw/ 是否已按当前配置完整抓取。"""
    if not raw_dir.exists():
        return False

    if expected_codes:
        for code in expected_codes:
            csv_path = raw_dir / f"{code}.csv"
            if not csv_path.exists():
                return False
        return True

    return any(raw_dir.glob("*.csv"))


def _run(step_name: str, cmd: list[str]) -> None:
    """运行子进程，失败时终止整个流程。"""
    print(f"\n{'='*60}")
    print(f"[步骤] {step_name}")
    print(f"  命令: {' '.join(cmd)}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"\n[ERROR] 步骤「{step_name}」返回非零退出码 {result.returncode}，流程已中止。")
        sys.exit(result.returncode)


def _print_recommendations() -> None:
    """读取最新 suggestion.json，打印推荐购买的股票。"""
    candidates_file = ROOT / "data" / "candidates" / "candidates_latest.json"
    if not candidates_file.exists():
        print("[ERROR] 找不到 candidates_latest.json，无法定位 suggestion.json。")
        return

    with open(candidates_file, encoding="utf-8") as f:
        pick_date: str = json.load(f).get("pick_date", "")

    if not pick_date:
        print("[ERROR] candidates_latest.json 中未设置 pick_date。")
        return

    suggestion_file = ROOT / "data" / "review" / pick_date / "suggestion.json"
    if not suggestion_file.exists():
        print(f"[ERROR] 找不到评分汇总文件：{suggestion_file}")
        return

    with open(suggestion_file, encoding="utf-8") as f:
        suggestion: dict = json.load(f)

    recommendations: list[dict] = suggestion.get("recommendations", [])
    min_score: float = suggestion.get("min_score_threshold", 0)
    total: int = suggestion.get("total_reviewed", 0)

    print(f"\n{'='*60}")
    print(f"  选股日期：{pick_date}")
    print(f"  评审总数：{total} 只   推荐门槛：score ≥ {min_score}")
    print(f"{'='*60}")

    if not recommendations:
        print("  暂无达标推荐股票。")
        return

    header = f"{'排名':>4}  {'代码':>8}  {'总分':>6}  {'信号':>10}  {'研判':>6}  备注"
    print(header)
    print("-" * len(header))
    for r in recommendations:
        rank        = r.get("rank",        "?")
        code        = r.get("code",        "?")
        score       = r.get("total_score", "?")
        signal_type = r.get("signal_type", "")
        verdict     = r.get("verdict",     "")
        comment     = r.get("comment",     "")
        score_str   = f"{score:.1f}" if isinstance(score, (int, float)) else str(score)
        print(f"{rank:>4}  {code:>8}  {score_str:>6}  {signal_type:>10}  {verdict:>6}  {comment}")
    print(f"\n推荐购买 {len(recommendations)} 只股票（详见 {suggestion_file}）")


def _check_python_version() -> None:
    if sys.version_info >= MIN_PYTHON:
        return
    required = ".".join(str(x) for x in MIN_PYTHON)
    current = sys.version.split()[0]
    print(f"[ERROR] 当前 Python 版本过低：{current}")
    print(f"        本工程依赖要求 Python >= {required}。")
    print("        请改用 python3.11 或 python3.12 运行，例如：")
    print("        /opt/homebrew/bin/python3.12 -m venv .venv")
    print("        source .venv/bin/activate")
    print("        python -m pip install -r requirements.txt")
    print("        python run_all.py --reviewer quant")
    sys.exit(1)


def main() -> None:
    _check_python_version()
    parser = argparse.ArgumentParser(description="AgentTrader 全流程自动运行脚本")
    parser.add_argument(
        "--reviewer",
        choices=["glm", "qwen", "gemini", "quant"],
        default="quant",
        help="选择图表分析模型：quant（量化评分，默认，无需 API Key）、glm（智谱GLM-4V-Flash）、qwen（通义千问VL）、gemini（Google Gemini）",
    )
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="跳过步骤 1（行情下载），直接从初选开始",
    )
    parser.add_argument(
        "--start-from", type=int, default=1, metavar="N",
        help="从第 N 步开始执行（1~4），跳过前面的步骤",
    )
    args = parser.parse_args()

    start = args.start_from

    if args.skip_fetch and start == 1:
        start = 2

    reviewer_info = REVIEWERS[args.reviewer]
    reviewer_name = reviewer_info["name"]
    reviewer_script = reviewer_info["script"]
    env_var = reviewer_info["env_var"]
    is_free = reviewer_info.get("free", False)

    # 检查 API Key
    import os
    if env_var is None:
        print(f"[INFO] 使用 {reviewer_name}（本地量化计算，无需 API Key）")
    elif not os.environ.get(env_var):
        print(f"[WARN] 未检测到环境变量 {env_var}")
        if is_free:
            print(f"       获取免费 API Key: https://open.bigmodel.cn/usercenter/apikeys")
        print(f"       步骤 4 可能失败，请先设置 {env_var}")
    else:
        if is_free:
            print(f"[INFO] 使用 {reviewer_name}（完全免费）")

    # ── 步骤 1：拉取 K 线数据 ─────────────────────────────────────────
    if start <= 1:
        raw_dir = ROOT / "data" / "raw"
        expected_codes = _load_expected_fetch_codes()
        if _has_all_expected_data(raw_dir, expected_codes=expected_codes) and not args.skip_fetch:
            print(f"\n{'='*60}")
            print("[步骤] 1  拉取 K 线数据 — 已跳过（数据已完整存在）")
            print(f"{'='*60}")
        elif args.skip_fetch:
            print(f"\n{'='*60}")
            print("[步骤] 1  拉取 K 线数据 — 已跳过（--skip-fetch）")
            print(f"{'='*60}")
        else:
            _run(
                "1  拉取 K 线数据（fetch_kline）",
                [PYTHON, "-m", "pipeline.fetch_kline"],
            )

    # ── 步骤 2：量化初选 ─────────────────────────────────────────────
    if start <= 2:
        _run(
            "2  量化初选（cli preselect）",
            [PYTHON, "-m", "pipeline.cli", "preselect"],
        )

    # ── 步骤 3：导出 K 线图（仅 LLM 模式） ──────────────────────────
    if start <= 3 and args.reviewer != "quant":
        _run(
            "3  导出 K 线图（export_kline_charts）",
            [PYTHON, str(ROOT / "dashboard" / "export_kline_charts.py")],
        )

    # ── 步骤 4：评分分析 ────────────────────────────────────────────
    if start <= 4:
        _run(
            f"4  {reviewer_name}评分（{args.reviewer}_review）",
            [PYTHON, str(reviewer_script)],
        )

    # ── 步骤 5：quant 模式 — 仅对 PASS 股票生成 K 线图 ────────────
    if args.reviewer == "quant" and start <= 5:
        candidates_file = ROOT / "data" / "candidates" / "candidates_latest.json"
        if candidates_file.exists():
            with open(candidates_file, encoding="utf-8") as f:
                pick_date: str = json.load(f).get("pick_date", "")
            suggestion_file = ROOT / "data" / "review" / pick_date / "suggestion.json"
            if suggestion_file.exists():
                with open(suggestion_file, encoding="utf-8") as f:
                    suggestion: dict = json.load(f)
                pass_codes = [r["code"] for r in suggestion.get("recommendations", []) if r.get("verdict") == "PASS"]
                if pass_codes:
                    print(f"\n{'='*60}")
                    print(f"[步骤] 5  导出 PASS 股票 K 线图（{len(pass_codes)} 只）")
                    print(f"{'='*60}")
                    cmd = [
                        PYTHON, str(ROOT / "dashboard" / "export_kline_charts.py"),
                        "--date", pick_date,
                        "--codes", *pass_codes,
                    ]
                    subprocess.run(cmd, cwd=str(ROOT))
                else:
                    print(f"\n{'='*60}")
                    print("[步骤] 5  导出 K 线图 — 已跳过（无 PASS 股票）")
                    print(f"{'='*60}")

    # ── 最后一步：打印推荐结果 ───────────────────────────────────────
    print(f"\n{'='*60}")
    print("[步骤] 6  推荐购买的股票" if args.reviewer == "quant" else "[步骤] 5  推荐购买的股票")
    _print_recommendations()


if __name__ == "__main__":
    main()
