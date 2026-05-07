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
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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

PROGRESS_JSON_PREFIX = "[PROGRESS_JSON]"
STAGE_PROGRESS = {
    "build_pool": {"label": "量化初选", "index": 2, "total": 6, "percent": 35},
    "build_candidates": {"label": "导出候选图表", "index": 3, "total": 6, "percent": 55},
    "pre_filter": {"label": "生成评分结果", "index": 4, "total": 6, "percent": 72},
    "score_review": {"label": "导出 PASS 图表", "index": 5, "total": 6, "percent": 88},
    "finalize": {"label": "输出推荐结果", "index": 6, "total": 6, "percent": 96},
    "completed": {"label": "已完成", "index": 6, "total": 6, "percent": 100},
}


def _emit_stage_progress(stage: str, message: str, *, percent: int | None = None, eta_seconds: int | None = None) -> None:
    info = STAGE_PROGRESS.get(stage, {})
    payload = {
        "kind": "stage",
        "stage": stage,
        "stage_label": info.get("label", stage),
        "stage_index": info.get("index"),
        "stage_total": info.get("total"),
        "percent": percent if percent is not None else info.get("percent", 0),
        "eta_seconds": eta_seconds,
        "message": message,
    }
    print(f"{PROGRESS_JSON_PREFIX} {json.dumps(payload, ensure_ascii=False)}", flush=True)


def _emit_observability_progress(
    *,
    stage: str,
    message: str,
    percent: int,
    ready_count: int | None = None,
    incremental_count: int | None = None,
    full_count: int | None = None,
    csv_imported_count: int | None = None,
    csv_failed_count: int | None = None,
    current: int | None = None,
    total: int | None = None,
    initial_completed: int | None = None,
    completed_in_run: int | None = None,
) -> None:
    payload = {
        "kind": "stage",
        "stage": stage,
        "percent": percent,
        "message": message,
        "ready_count": ready_count,
        "incremental_count": incremental_count,
        "full_count": full_count,
        "csv_imported_count": csv_imported_count,
        "csv_failed_count": csv_failed_count,
        "current": current,
        "total": total,
        "initial_completed": initial_completed,
        "completed_in_run": completed_in_run,
    }
    print(f"{PROGRESS_JSON_PREFIX} {json.dumps(payload, ensure_ascii=False)}", flush=True)


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


def _load_env_var(name: str) -> str:
    """优先读取环境变量，缺失时回退到项目根目录 .env。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value

    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""

    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            if key.strip() != name:
                continue
            return raw.strip().strip("'\"")
    except Exception:
        return ""

    return ""


def _sync_candidates_to_db() -> None:
    """将候选数据同步到数据库（阶段7：结果数据库化）"""
    import json
    candidates_file = ROOT / "data" / "candidates" / "candidates_latest.json"
    if not candidates_file.exists():
        print("[INFO] 候选文件不存在，跳过数据库同步")
        return

    try:
        with open(candidates_file, encoding="utf-8") as f:
            data = json.load(f)

        pick_date = data.get("pick_date")
        candidates = data.get("candidates", [])

        if not pick_date or not candidates:
            print("[INFO] 候选数据为空，跳过数据库同步")
            return

        # 调用候选服务保存到数据库
        import sys
        sys.path.insert(0, str(ROOT / "backend"))
        from app.services.candidate_service import get_candidate_service

        candidate_service = get_candidate_service()
        count = candidate_service.save_candidates(
            pick_date=pick_date,
            candidates=candidates,
            strategy="b1",
            clean_existing=True,
        )

        print(f"[INFO] 候选数据已同步到数据库: pick_date={pick_date}, count={count}")

    except Exception as e:
        print(f"[WARNING] 候选数据同步到数据库失败: {e}")
        import traceback
        traceback.print_exc()


def _sync_raw_csv_to_db_if_needed(raw_dir: Path, *, latest_trade_date: str | None = None) -> None:
    """在 --db 模式下，必要时把现有 raw CSV 回灌到数据库。

    背景：
    - 当 data/raw 已完整且是最新交易日时，步骤 1 会被自动跳过。
    - 但如果数据库还没有 K 线数据，仅跳过抓取会导致“raw 有数据、数据库为空”。
    """
    if not raw_dir.exists():
        print("[INFO] raw 目录不存在，跳过数据库回灌。")
        return

    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        print("[INFO] raw 目录中没有 CSV 文件，跳过数据库回灌。")
        return

    try:
        if str(ROOT / "backend") not in sys.path:
            sys.path.insert(0, str(ROOT / "backend"))

        from app.services.daily_data_service import get_daily_data_service
        from app.services.tushare_service import TushareService

        tushare_service = TushareService()
        data_status = tushare_service.check_data_status()
        raw_status = data_status.get("raw_data", {}) if isinstance(data_status, dict) else {}
        db_latest_date = str(raw_status.get("latest_date") or "").strip() or None
        db_stock_count = int(raw_status.get("stock_count") or 0)
        csv_count = len(csv_files)

        needs_import = (
            not raw_status.get("exists")
            or db_stock_count < csv_count
            or (latest_trade_date and db_latest_date != latest_trade_date)
        )
        if not needs_import:
            print(
                f"[INFO] 数据库 K 线已就绪，跳过 CSV 回灌。"
                f" db_stock_count={db_stock_count} latest={db_latest_date}"
            )
            return

        print("\n" + "=" * 60)
        print("[步骤] 1.5  raw CSV 回灌数据库（--db 模式）")
        print(
            f"[INFO] 触发原因: db_exists={raw_status.get('exists')} | "
            f"db_stock_count={db_stock_count}/{csv_count} | "
            f"db_latest={db_latest_date} | trade_latest={latest_trade_date}"
        )
        print("=" * 60)

        # 计算初始已完成数量（数据库中已有数据的股票数）
        # 这些股票的 CSV 会被跳过或快速处理
        initial_completed = db_stock_count if raw_status.get("exists") else 0

        # 定义进度回调函数
        def progress_cb(current, total, code, status):
            percent = 5 + int((current / total) * 3)  # 5% -> 8%
            # 计算 actual_total：实际需要处理的总数 = 总数 - 初始已完成
            actual_total = max(0, total - initial_completed)
            actual_current = max(0, current - initial_completed) if current > initial_completed else 0
            # 确保 current 不超过 total
            display_current = min(current, total)

            _emit_observability_progress(
                stage="fetch_data",
                percent=percent,
                message=f"CSV 回灌中: {current}/{total} ({code})",
                current=display_current,
                total=total,
                initial_completed=initial_completed,
                completed_in_run=actual_current,
            )

        result = get_daily_data_service().batch_import_csv_fast(raw_dir, progress_callback=progress_cb)
        imported = int(result.get("imported") or 0)
        failed = int(result.get("failed") or 0)
        # 计算实际在本次运行中处理的数量
        completed_in_run = imported
        if result.get("success"):
            print(
                f"[INFO] CSV 回灌完成: imported={imported} "
                f"failed={failed}"
            )
            _emit_observability_progress(
                stage="fetch_data",
                percent=8,
                message=f"CSV 回灌完成: imported={imported} failed={failed}",
                current=csv_count,
                total=csv_count,
                initial_completed=initial_completed,
                completed_in_run=completed_in_run,
                csv_imported_count=imported,
                csv_failed_count=failed,
            )
        else:
            print(f"[WARN] CSV 回灌未完成: {result.get('message')}")
    except Exception as e:
        print(f"[WARNING] raw CSV 回灌数据库失败: {e}")
        import traceback
        traceback.print_exc()


def _get_local_latest_date(raw_dir: Path) -> str | None:
    """扫描 data/raw/ 中 CSV 的最新日期。"""
    latest_date: str | None = None
    for csv_path in raw_dir.glob("*.csv"):
        try:
            with open(csv_path, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                continue
            date_value = str(rows[-1].get("date", "")).strip()
            if len(date_value) >= 10:
                date_value = date_value[:10]
            if date_value and (latest_date is None or date_value > latest_date):
                latest_date = date_value
        except Exception:
            continue
    return latest_date


def _get_latest_date_from_csv(csv_path: Path) -> str | None:
    """读取单个 CSV 中的最新交易日，格式返回 YYYYMMDD。"""
    try:
        df = pd.read_csv(csv_path)
        if "date" in df.columns and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            latest = df["date"].max()
            return latest.strftime("%Y%m%d")
    except Exception:
        return None
    return None


def _assess_raw_data_progress(raw_dir: Path, expected_codes: set[str], latest_trade_date: str | None) -> dict[str, Any]:
    """评估 raw CSV 的真实抓取进度。

    关注三类问题：
    - 文件缺失
    - 文件存在但无有效日期
    - 文件最新日期落后于最新交易日
    """
    if not raw_dir.exists():
        return {
            "expected_total": len(expected_codes),
            "ready_codes": 0,
            "missing_codes": sorted(expected_codes),
            "stale_codes": [],
            "invalid_codes": [],
            "latest_local_date": None,
            "is_complete": False,
        }

    ready_codes = 0
    missing_codes: list[str] = []
    stale_codes: list[str] = []
    invalid_codes: list[str] = []
    latest_local_date: str | None = None

    for code in sorted(expected_codes):
        csv_path = raw_dir / f"{code}.csv"
        if not csv_path.exists():
            missing_codes.append(code)
            continue

        csv_latest = _get_latest_date_from_csv(csv_path)
        if not csv_latest:
            invalid_codes.append(code)
            continue

        csv_latest_fmt = f"{csv_latest[:4]}-{csv_latest[4:6]}-{csv_latest[6:]}"
        if latest_local_date is None or csv_latest_fmt > latest_local_date:
            latest_local_date = csv_latest_fmt

        if latest_trade_date and csv_latest_fmt < latest_trade_date:
            stale_codes.append(code)
            continue

        ready_codes += 1

    is_complete = not missing_codes and not stale_codes and not invalid_codes and ready_codes == len(expected_codes)
    return {
        "expected_total": len(expected_codes),
        "ready_codes": ready_codes,
        "missing_codes": missing_codes,
        "stale_codes": stale_codes,
        "invalid_codes": invalid_codes,
        "latest_local_date": latest_local_date,
        "is_complete": is_complete,
    }


def _get_latest_trade_date() -> str | None:
    """读取用于过期判断的有效最新交易日；失败时返回 None。"""
    token = _load_env_var("TUSHARE_TOKEN")
    if not token:
        return None

    try:
        import tushare as ts

        pro = ts.pro_api(token)
        today = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
        df = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=today)
        if df is None or df.empty:
            return None

        trade_days = df[df["is_open"] == 1].sort_values("cal_date", ascending=False)
        if trade_days.empty:
            return None

        latest = str(trade_days.iloc[0]["cal_date"])
        latest_trade_date = f"{latest[:4]}-{latest[4:6]}-{latest[6:]}"
        bj_now = datetime.now(ZoneInfo("Asia/Shanghai"))

        if latest_trade_date < bj_now.strftime("%Y-%m-%d"):
            return latest_trade_date

        if bj_now.hour < 17:
            previous_days = [
                f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}"
                for day in trade_days["cal_date"].tolist()
                if f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}" < latest_trade_date
            ]
            return previous_days[0] if previous_days else latest_trade_date

        base_df = pro.daily(ts_code="000001.SZ", start_date=latest, end_date=latest)
        if base_df is not None and not base_df.empty:
            return latest_trade_date

        previous_days = [
            f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}"
            for day in trade_days["cal_date"].tolist()
            if f"{str(day)[:4]}-{str(day)[4:6]}-{str(day)[6:]}" < latest_trade_date
        ]
        return previous_days[0] if previous_days else latest_trade_date
    except Exception as exc:
        print(f"[WARN] 获取最新交易日失败，将继续执行抓取避免使用旧数据: {exc}")
        return None


def _run(step_name: str, cmd: list[str], *, stage: str | None = None) -> None:
    """运行子进程，失败时终止整个流程。"""
    started_at = time.time()
    if stage:
        _emit_stage_progress(stage, f"{step_name} 开始")
    print(f"\n{'='*60}")
    print(f"[步骤] {step_name}")
    print(f"  命令: {' '.join(cmd)}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        if stage:
            elapsed_seconds = max(0, int(time.time() - started_at))
            _emit_stage_progress(stage, f"{step_name} 失败，已在 {elapsed_seconds} 秒后中止", eta_seconds=None)
        print(f"\n[ERROR] 步骤「{step_name}」返回非零退出码 {result.returncode}，流程已中止。")
        sys.exit(result.returncode)
    if stage:
        _emit_stage_progress(stage, f"{step_name} 完成", eta_seconds=0)


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
        help="从第 N 步开始执行（1~5），跳过前面的步骤",
    )
    parser.add_argument(
        "--resume-from", type=str, metavar="STEP",
        choices=["fetch_data", "csv_import", "build_pool", "build_candidates", "pre_filter", "score_review", "finalize"],
        help="从指定步骤恢复执行（断点续传），可选值: fetch_data, csv_import, build_pool, build_candidates, pre_filter, score_review, finalize",
    )
    parser.add_argument(
        "--db", action="store_true",
        help="将 K 线数据写入数据库（传递给 fetch_kline 步骤）",
    )
    args = parser.parse_args()
    target_date = os.environ.get("TARGET_DATE", "").strip() or None

    # 处理 --resume-from 参数（断点续传）
    if args.resume_from:
        resume_step_map = {
            "fetch_data": 1,
            "csv_import": 1,
            "build_pool": 2,
            "build_candidates": 3,
            "pre_filter": 4,
            "score_review": 5,
            "finalize": 6,
        }
        start = resume_step_map.get(args.resume_from, 1)
        if args.resume_from == "fetch_data":
            # 恢复到 fetch_data 时，不跳过抓取
            skip_fetch = False
        else:
            # 其他恢复点都跳过 fetch
            skip_fetch = True
        print(f"[INFO] 断点续传: 从步骤 '{args.resume_from}' (步骤 {start}) 开始执行")
    else:
        start = args.start_from
        skip_fetch = args.skip_fetch

    if skip_fetch and start == 1:
        start = 2

    reviewer_info = REVIEWERS[args.reviewer]
    reviewer_name = reviewer_info["name"]
    reviewer_script = reviewer_info["script"]
    env_var = reviewer_info["env_var"]
    is_free = reviewer_info.get("free", False)

    # 检查 API Key
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
        latest_trade_date = _get_latest_trade_date() if not args.skip_fetch else None
        raw_progress = _assess_raw_data_progress(raw_dir, expected_codes=expected_codes, latest_trade_date=latest_trade_date)
        local_latest_date = raw_progress.get("latest_local_date")
        has_complete_data = bool(raw_progress.get("is_complete"))

        if has_complete_data and not args.skip_fetch and latest_trade_date and local_latest_date == latest_trade_date:
            print(f"\n{'='*60}")
            print(f"[步骤] 1  拉取 K 线数据 — 已跳过（数据完整且已是最新交易日 {latest_trade_date}）")
            print(f"{'='*60}")
            if args.db:
                _sync_raw_csv_to_db_if_needed(raw_dir, latest_trade_date=latest_trade_date)
        elif args.skip_fetch:
            print(f"\n{'='*60}")
            print("[步骤] 1  拉取 K 线数据 — 已跳过（--skip-fetch）")
            print(f"{'='*60}")
            if args.db:
                _sync_raw_csv_to_db_if_needed(raw_dir, latest_trade_date=local_latest_date)
        else:
            missing_count = len(raw_progress.get("missing_codes", []))
            stale_count = len(raw_progress.get("stale_codes", []))
            invalid_count = len(raw_progress.get("invalid_codes", []))
            ready_count = raw_progress.get("ready_codes", 0)
            expected_total = raw_progress.get("expected_total", 0)

            if expected_total:
                print(
                    f"[INFO] 当前 CSV 进度: 已就绪 {ready_count}/{expected_total}"
                    f" | 缺失 {missing_count} | 过期 {stale_count} | 异常 {invalid_count}"
                )
            if latest_trade_date:
                print(f"[INFO] 最新交易日: {latest_trade_date} | 本地 CSV 最新日期: {local_latest_date or '-'}")

            # 判断是否需要增量更新还是全量抓取
            # 只有当几乎没有任何数据时（ready_count < expected_total 的 10%）才使用全量抓取
            use_incremental = ready_count > (expected_total * 0.1)

            if use_incremental:
                print(f"[步骤] 1  拉取 K 线数据 — 增量模式（只更新缺失/过期/异常的股票）")
            else:
                print(f"[步骤] 1  拉取 K 线数据 — 全量模式（数据缺失较多，重新抓取全部）")

            if args.db:
                _sync_raw_csv_to_db_if_needed(
                    raw_dir,
                    latest_trade_date=latest_trade_date or local_latest_date,
                )

            fetch_cmd = [PYTHON, "-m", "pipeline.fetch_kline"]
            if use_incremental:
                fetch_cmd.append("--incremental")
            if args.db:
                fetch_cmd.append("--db")

            _run(
                f"1  拉取 K 线数据（fetch_kline - {'增量' if use_incremental else '全量'}）",
                fetch_cmd,
            )

    # ── 步骤 2：量化初选 ─────────────────────────────────────────────
    if start <= 2:
        preselect_cmd = [PYTHON, "-m", "pipeline.cli", "preselect"]
        if target_date:
            preselect_cmd.extend(["--date", target_date, "--end-date", target_date])
        _run(
            "2  量化初选（cli preselect）",
            preselect_cmd,
            stage="build_pool",
        )

        # ── 步骤 2.5：候选数据入库（数据库模式）──────────────────────
        if args.db:
            _sync_candidates_to_db()

    # ── 步骤 3：导出 K 线图（仅 LLM 模式） ──────────────────────────
    if start <= 3 and args.reviewer != "quant":
        _run(
            "3  导出 K 线图（export_kline_charts）",
            [PYTHON, str(ROOT / "dashboard" / "export_kline_charts.py")],
            stage="build_candidates",
        )

    # ── 步骤 4：评分分析 ────────────────────────────────────────────
    if start <= 4:
        _run(
            f"4  {reviewer_name}评分（{args.reviewer}_review）",
            [PYTHON, str(reviewer_script)],
            stage="pre_filter",
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
                    cmd = [
                        PYTHON, str(ROOT / "dashboard" / "export_kline_charts.py"),
                        "--date", pick_date,
                        "--codes", *pass_codes,
                    ]
                    _run(
                        f"5  导出 PASS 股票 K 线图（{len(pass_codes)} 只）",
                        cmd,
                        stage="score_review",
                    )
                else:
                    print(f"\n{'='*60}")
                    print("[步骤] 5  导出 K 线图 — 已跳过（无 PASS 股票）")
                    print(f"{'='*60}")
                    _emit_stage_progress("score_review", "5  导出 PASS 股票 K 线图已跳过（无 PASS 股票）", eta_seconds=0)

    # ── 最后一步：打印推荐结果 ───────────────────────────────────────
    _emit_stage_progress("finalize", "6  输出推荐结果开始")
    print(f"\n{'='*60}")
    print("[步骤] 6  推荐购买的股票" if args.reviewer == "quant" else "[步骤] 5  推荐购买的股票")
    _print_recommendations()
    _emit_stage_progress("completed", "全量初始化流程完成", eta_seconds=0)


if __name__ == "__main__":
    main()
