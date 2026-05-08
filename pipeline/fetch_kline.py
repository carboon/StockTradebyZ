from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import random
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, List, Optional
import os

import pandas as pd
import tushare as ts
import yaml
from backend.app.utils.stock_metadata import resolve_ts_code
from backend.app.utils.tushare_rate_limit import acquire_tushare_slot, MAX_REQUESTS_PER_WINDOW, WINDOW_SECONDS

warnings.filterwarnings("ignore")

# --------------------------- 数据库写入（可选） --------------------------- #
_DB_MODE = False  # 由 main() 中 --db 参数控制
_DB_SESSION_FACTORIES: dict[str, Any] = {}


def _get_db_session_factory(db_url: str):
    factory = _DB_SESSION_FACTORIES.get(db_url)
    if factory is not None:
        return factory

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url)
    factory = sessionmaker(bind=engine)
    _DB_SESSION_FACTORIES[db_url] = factory
    return factory


def _save_to_db(code: str, df, db_url: str) -> None:
    """将 K 线数据写入数据库。每个线程使用独立 session。"""
    if df is None or df.empty:
        return
    from backend.app.services.kline_service import save_daily_data

    Session = _get_db_session_factory(db_url)
    db = Session()
    try:
        save_daily_data(db, code, df)
    except Exception as exc:
        logging.getLogger("fetch_from_stocklist").error("写入数据库失败 %s: %s", code, exc)
    finally:
        db.close()

# --------------------------- pandas 兼容补丁 --------------------------- #
# tushare 内部使用了 fillna(method='ffill'/'bfill')，在 pandas 2.2+ 中已移除该参数。
# 此补丁将旧式调用自动转发到 ffill()/bfill()，无需降级 pandas。
import pandas as _pd

_orig_fillna = _pd.DataFrame.fillna

def _patched_fillna(self, value=None, *, method=None, axis=None, inplace=False, limit=None, **kwargs):
    if method is not None:
        if method == "ffill":
            result = self.ffill(axis=axis, inplace=inplace, limit=limit)
        elif method == "bfill":
            result = self.bfill(axis=axis, inplace=inplace, limit=limit)
        else:
            raise ValueError(f"Unsupported fillna method: {method}")
        return result
    return _orig_fillna(self, value, axis=axis, inplace=inplace, limit=limit, **kwargs)

_pd.DataFrame.fillna = _patched_fillna  # type: ignore[method-assign]

_orig_series_fillna = _pd.Series.fillna

def _patched_series_fillna(self, value=None, *, method=None, axis=None, inplace=False, limit=None, **kwargs):
    if method is not None:
        if method == "ffill":
            result = self.ffill(axis=axis, inplace=inplace, limit=limit)
        elif method == "bfill":
            result = self.bfill(axis=axis, inplace=inplace, limit=limit)
        else:
            raise ValueError(f"Unsupported fillna method: {method}")
        return result
    return _orig_series_fillna(self, value, axis=axis, inplace=inplace, limit=limit, **kwargs)

_pd.Series.fillna = _patched_series_fillna  # type: ignore[method-assign]

# --------------------------- 全局日志配置 --------------------------- #
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LOG_DIR = _PROJECT_ROOT / "data" / "logs"
_RUN_STATE_DIR = _PROJECT_ROOT / "data" / "run"
_CHECKPOINT_VERSION = 1
_PROGRESS_JSON_PREFIX = "[PROGRESS_JSON]"

def _resolve_cfg_path(path_like: str | Path, base_dir: Path = _PROJECT_ROOT) -> Path:
    """将配置中的路径统一解析为绝对路径：相对路径基于项目根目录。"""
    p = Path(path_like)
    return p if p.is_absolute() else (base_dir / p)

def _default_log_path() -> Path:
    today = dt.date.today().strftime("%Y-%m-%d")
    return _DEFAULT_LOG_DIR / f"fetch_{today}.log"


def _load_env_var(name: str) -> str:
    """优先读取环境变量，缺失时回退到项目根目录 .env。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value

    env_path = _PROJECT_ROOT / ".env"
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

def setup_logging(log_path: Optional[Path] = None) -> None:
    """初始化日志：同时输出到 stdout 和指定文件。"""
    if log_path is None:
        log_path = _default_log_path()
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, mode="a", encoding="utf-8"),
        ],
    )

logger = logging.getLogger("fetch_from_stocklist")

# --------------------------- 限流/封禁处理配置 --------------------------- #
COOLDOWN_SECS = 600
BAN_PATTERNS = (
    "访问频繁", "请稍后", "超过频率", "频繁访问",
    "too many requests", "429",
    "forbidden", "403",
    "max retries exceeded"
)

def _looks_like_ip_ban(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    return any(pat in msg for pat in BAN_PATTERNS)

class RateLimitError(RuntimeError):
    """表示命中限流/封禁，需要长时间冷却后重试。"""
    pass

def _cool_sleep(base_seconds: int) -> None:
    jitter = random.uniform(0.9, 1.2)
    sleep_s = max(1, int(base_seconds * jitter))
    logger.warning("疑似被限流/封禁，进入冷却期 %d 秒...", sleep_s)
    time.sleep(sleep_s)

# --------------------------- 历史K线（Tushare 日线，固定qfq） --------------------------- #
pro: Optional[ts.pro_api] = None  # 模块级会话

def set_api(session) -> None:
    """由外部(比如GUI)注入已创建好的 ts.pro_api() 会话"""
    global pro
    pro = session
    

def _to_ts_code(code: str) -> str:
    """把6位code映射到标准 ts_code 后缀。"""
    return resolve_ts_code(code)


def _fetch_daily_basic(ts_code: str, start: str, end: str) -> pd.DataFrame:
    acquire_tushare_slot("daily_basic")
    df = pro.daily_basic(
        ts_code=ts_code,
        start_date=start,
        end_date=end,
        fields="ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,free_share,circ_mv",
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "turnover_rate", "turnover_rate_f", "volume_ratio", "free_share", "circ_mv"])
    df = df.rename(columns={"trade_date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df[["date", "turnover_rate", "turnover_rate_f", "volume_ratio", "free_share", "circ_mv"]].copy()


def _fetch_moneyflow(ts_code: str, start: str, end: str) -> pd.DataFrame:
    acquire_tushare_slot("moneyflow")
    df = pro.moneyflow(
        ts_code=ts_code,
        start_date=start,
        end_date=end,
        fields=(
            "ts_code,trade_date,buy_sm_amount,sell_sm_amount,"
            "buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,"
            "buy_elg_amount,sell_elg_amount,net_mf_amount"
        ),
    )
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "buy_sm_amount",
                "sell_sm_amount",
                "buy_md_amount",
                "sell_md_amount",
                "buy_lg_amount",
                "sell_lg_amount",
                "buy_elg_amount",
                "sell_elg_amount",
                "net_mf_amount",
            ]
        )
    df = df.rename(columns={"trade_date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df[
        [
            "date",
            "buy_sm_amount",
            "sell_sm_amount",
            "buy_md_amount",
            "sell_md_amount",
            "buy_lg_amount",
            "sell_lg_amount",
            "buy_elg_amount",
            "sell_elg_amount",
            "net_mf_amount",
        ]
    ].copy()


def _get_kline_tushare(code: str, start: str, end: str) -> pd.DataFrame:
    ts_code = _to_ts_code(code)
    try:
        acquire_tushare_slot("pro_bar")
        df = ts.pro_bar(
            ts_code=ts_code,
            adj="qfq",
            start_date=start,
            end_date=end,
            freq="D",
            api=pro
        )
    except Exception as e:
        if _looks_like_ip_ban(e):
            raise RateLimitError(str(e)) from e
        raise

    if df is None or df.empty:
        return pd.DataFrame()

    df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
        ["date", "open", "close", "high", "low", "volume"]
    ].copy()
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.merge(_fetch_daily_basic(ts_code, start, end), on="date", how="left")
    df = df.merge(_fetch_moneyflow(ts_code, start, end), on="date", how="left")
    return df.sort_values("date").reset_index(drop=True)

def validate(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    if df["date"].isna().any():
        raise ValueError("存在缺失日期！")
    if (df["date"] > pd.Timestamp.today()).any():
        raise ValueError("数据包含未来日期，可能抓取错误！")
    return df


def _format_eta(seconds: Optional[int]) -> Optional[str]:
    if seconds is None or seconds < 0:
        return None
    minutes, remain = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}小时{minutes}分"
    if minutes > 0:
        return f"{minutes}分{remain}秒"
    return f"{remain}秒"


def _calc_fetch_percent(current: int, total: int) -> int:
    """将抓取进度映射到全流程的步骤 1 区间。"""
    if total <= 0:
        return 5
    return min(30, 5 + int((current / total) * 25))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _build_checkpoint_path(codes: List[str], start: str, end: str, out_dir: Path) -> Path:
    identity = {
        "version": _CHECKPOINT_VERSION,
        "start": start,
        "end": end,
        "out_dir": str(out_dir.resolve()),
        "codes_hash": hashlib.sha1(",".join(codes).encode("utf-8")).hexdigest(),
    }
    digest = hashlib.sha1(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return _RUN_STATE_DIR / f"fetch_kline_{digest}.json"


def _load_checkpoint(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("读取断点文件失败，将忽略并重新开始: %s | %s", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _restore_checkpoint_state(
    checkpoint: Optional[dict[str, Any]],
    codes: List[str],
    out_dir: Path,
) -> tuple[set[str], dict[str, str]]:
    if not checkpoint:
        return set(), {}

    code_set = set(codes)
    completed: set[str] = set()
    for code in checkpoint.get("completed_codes", []):
        if code in code_set and (out_dir / f"{code}.csv").exists():
            completed.add(code)

    failed_raw = checkpoint.get("failed_codes", {})
    failed: dict[str, str] = {}
    if isinstance(failed_raw, dict):
        for code, reason in failed_raw.items():
            if code in code_set and code not in completed:
                failed[str(code)] = str(reason or "抓取失败")

    return completed, failed


def _save_checkpoint(
    path: Path,
    *,
    codes: List[str],
    start: str,
    end: str,
    out_dir: Path,
    completed_codes: set[str],
    failed_codes: dict[str, str],
) -> None:
    payload = {
        "version": _CHECKPOINT_VERSION,
        "updated_at": dt.datetime.now().isoformat(),
        "start": start,
        "end": end,
        "out_dir": str(out_dir.resolve()),
        "total": len(codes),
        "completed_codes": sorted(completed_codes),
        "failed_codes": failed_codes,
        "resume_supported": True,
    }
    _atomic_write_json(path, payload)


def _clear_checkpoint(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("清理断点文件失败: %s | %s", path, exc)


def _emit_progress(payload: dict[str, Any]) -> None:
    print(f"{_PROGRESS_JSON_PREFIX} {json.dumps(payload, ensure_ascii=False)}", flush=True)


def _build_fetch_progress_payload(
    *,
    current: int,
    total: int,
    current_code: Optional[str],
    initial_completed: int,
    completed_in_run: int,
    failed_count: int,
    eta_seconds: Optional[int],
    message: str,
) -> dict[str, Any]:
    percent = _calc_fetch_percent(current, total)
    return {
        "kind": "fetch",
        "stage": "fetch_data",
        "stage_label": "抓取原始数据",
        "current": current,
        "total": total,
        "current_code": current_code,
        "initial_completed": initial_completed,
        "completed_in_run": completed_in_run,
        "failed_count": failed_count,
        "resume_supported": True,
        "eta_seconds": eta_seconds,
        "eta_label": _format_eta(eta_seconds),
        "percent": percent,
        "message": message,
    }

# --------------------------- 读取 stocklist.csv & 过滤板块 --------------------------- #

def _filter_by_boards(df: pd.DataFrame, include: set[str] | None = None, exclude: set[str] | None = None) -> pd.DataFrame:
    """按板块过滤股票。

    include 非空时，仅保留指定板块；否则按 exclude 排除。
    板块标识：main / gem / star / bj
    """
    ts = df["ts_code"].astype(str).str.upper()
    num = ts.str.extract(r"(\d{6})", expand=False).str.zfill(6)
    is_gem  = (ts.str.endswith(".SZ")) & num.str.startswith(("300", "301"))
    is_star = (ts.str.endswith(".SH")) & num.str.startswith(("688",))
    is_bj   = (ts.str.endswith(".BJ")) | num.str.startswith(("4", "8"))

    if include is not None:
        mask = pd.Series(False, index=df.index)
        if "main" in include:
            mask |= ~(is_gem | is_star | is_bj)
        if "gem" in include:
            mask |= is_gem
        if "star" in include:
            mask |= is_star
        if "bj" in include:
            mask |= is_bj
    else:
        mask = pd.Series(True, index=df.index)
        if exclude and "gem" in exclude:
            mask &= ~is_gem
        if exclude and "star" in exclude:
            mask &= ~is_star
        if exclude and "bj" in exclude:
            mask &= ~is_bj

    return df[mask].copy()


def load_codes_from_stocklist(stocklist_csv: Path, include_boards: set[str] | None = None, exclude_boards: set[str] | None = None) -> List[str]:
    df = pd.read_csv(stocklist_csv)
    df = _filter_by_boards(df, include=include_boards, exclude=exclude_boards)
    codes = df["symbol"].astype(str).str.zfill(6).tolist()
    codes = list(dict.fromkeys(codes))  # 去重保持顺序
    if include_boards:
        logger.info("从 %s 读取到 %d 只股票（指定板块：%s）",
                    stocklist_csv, len(codes), ",".join(sorted(include_boards)))
    else:
        logger.info("从 %s 读取到 %d 只股票（排除板块：%s）",
                    stocklist_csv, len(codes), ",".join(sorted(exclude_boards)) if exclude_boards else "无")
    return codes

# --------------------------- 单只抓取（全量覆盖保存） --------------------------- #
def fetch_one(
    code: str,
    start: str,
    end: str,
    out_dir: Path,
    db_url: Optional[str] = None,
) -> dict[str, Any]:
    csv_path = out_dir / f"{code}.csv"
    result = {
        "code": code,
        "success": False,
        "empty": False,
        "error": None,
    }

    for attempt in range(1, 4):
        try:
            new_df = _get_kline_tushare(code, start, end)
            result["empty"] = bool(new_df.empty)
            if new_df.empty:
                logger.debug("%s 无数据，生成空表。", code)
                new_df = pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])
            new_df = validate(new_df)
            new_df.to_csv(csv_path, index=False)  # 直接覆盖保存
            # 写入数据库（如果启用）
            if db_url:
                _save_to_db(code, new_df, db_url)
            result["success"] = True
            return result
        except Exception as e:
            if _looks_like_ip_ban(e):
                logger.error(f"{code} 第 {attempt} 次抓取疑似被封禁，沉睡 {COOLDOWN_SECS} 秒")
                _cool_sleep(COOLDOWN_SECS)
            else:
                silent_seconds = 30 * attempt
                logger.info(f"{code} 第 {attempt} 次抓取失败，{silent_seconds} 秒后重试：{e}")
                time.sleep(silent_seconds)

    result["error"] = "三次抓取均失败"
    logger.error("%s 三次抓取均失败，已跳过！", code)
    return result


def full_fetch(
    codes: List[str],
    start: str,
    end: str,
    out_dir: Path,
    workers: int = 8,
    checkpoint_path: Optional[Path] = None,
    db_url: Optional[str] = None,
) -> dict[str, Any]:
    """智能抓取并支持断点恢复。"""
    if not codes:
        raise ValueError("股票代码列表为空")

    total = len(codes)
    ready_codes, incremental_codes, full_codes = _classify_codes_by_local_csv(codes, out_dir, end)
    checkpoint_path = checkpoint_path or _build_checkpoint_path(codes, start, end, out_dir)
    checkpoint = _load_checkpoint(checkpoint_path)
    completed_codes, failed_codes = _restore_checkpoint_state(checkpoint, codes, out_dir)
    completed_codes.update(ready_codes)
    initial_completed = len(completed_codes)
    remaining_incremental_codes = [code for code in incremental_codes if code not in completed_codes]
    remaining_full_codes = [code for code in full_codes if code not in completed_codes]
    remaining_codes = remaining_incremental_codes + remaining_full_codes

    if initial_completed > 0:
        logger.info(
            "检测到可恢复的抓取进度 | 已完成:%d/%d | 剩余:%d | 断点文件:%s",
            initial_completed,
            total,
            len(remaining_codes),
            checkpoint_path.resolve(),
        )
    else:
        logger.info("未检测到历史断点，将从头开始抓取。")

    logger.info(
        "本地 CSV 分类 | 已完整:%d | 增量补齐:%d | 全量重抓:%d",
        len(ready_codes),
        len(remaining_incremental_codes),
        len(remaining_full_codes),
    )
    print(
        f"[INFO] 本地 CSV 分类 | 已完整 {len(ready_codes)} | 增量补齐 {len(remaining_incremental_codes)} | 全量重抓 {len(remaining_full_codes)}",
        flush=True,
    )
    _emit_progress({
        "kind": "fetch",
        "stage": "fetch_data",
        "stage_label": "抓取原始数据",
        "percent": 9,
        "message": (
            f"本地 CSV 分类 | 已完整 {len(ready_codes)} | "
            f"增量补齐 {len(remaining_incremental_codes)} | 全量重抓 {len(remaining_full_codes)}"
        ),
        "ready_count": len(ready_codes),
        "incremental_count": len(remaining_incremental_codes),
        "full_count": len(remaining_full_codes),
    })

    _save_checkpoint(
        checkpoint_path,
        codes=codes,
        start=start,
        end=end,
        out_dir=out_dir,
        completed_codes=completed_codes,
        failed_codes=failed_codes,
    )

    if not remaining_codes:
        payload = _build_fetch_progress_payload(
            current=total,
            total=total,
            current_code=None,
            initial_completed=initial_completed,
            completed_in_run=0,
            failed_count=0,
            eta_seconds=0,
            message="抓取原始数据已全部完成",
        )
        _emit_progress(payload)
        _clear_checkpoint(checkpoint_path)
        return {
            "success": True,
            "total": total,
            "completed": total,
            "failed": 0,
            "initial_completed": initial_completed,
            "checkpoint_path": str(checkpoint_path),
        }

    run_started_at = time.time()
    completed_in_run = 0
    failed_in_run = 0
    last_emit_at = 0.0
    emit_interval = 2.0

    def maybe_emit_progress(current_code: Optional[str], force: bool = False) -> None:
        nonlocal last_emit_at
        processed_in_run = completed_in_run + failed_in_run
        current_completed = len(completed_codes)
        now = time.time()
        should_emit = force or (
            processed_in_run > 0 and (
                now - last_emit_at >= emit_interval
                or processed_in_run == len(remaining_codes)
                or processed_in_run % 100 == 0
            )
        )
        if not should_emit:
            return

        elapsed_seconds = max(0.0, now - run_started_at)
        remaining_to_process = max(0, len(remaining_codes) - processed_in_run)
        eta_seconds: Optional[int] = None
        if processed_in_run > 0 and remaining_to_process > 0 and elapsed_seconds > 0:
            avg_seconds = elapsed_seconds / processed_in_run
            eta_seconds = max(0, int(avg_seconds * remaining_to_process))
        elif remaining_to_process == 0:
            eta_seconds = 0

        message = f"抓取原始数据 {current_completed}/{total}"
        if current_code:
            message += f" | 当前 {current_code}"
        if failed_codes:
            message += f" | 失败 {len(failed_codes)}"
        eta_label = _format_eta(eta_seconds)
        if eta_label:
            message += f" | 预计剩余 {eta_label}"

        payload = _build_fetch_progress_payload(
            current=current_completed,
            total=total,
            current_code=current_code,
            initial_completed=initial_completed,
            completed_in_run=completed_in_run,
            failed_count=len(failed_codes),
            eta_seconds=eta_seconds,
            message=message,
        )
        logger.info(message)
        _emit_progress(payload)
        last_emit_at = now

    maybe_emit_progress(None, force=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for code in remaining_incremental_codes:
            futures[executor.submit(fetch_one_incremental, code, end, out_dir, None, db_url)] = code
        for code in remaining_full_codes:
            futures[executor.submit(fetch_one, code, start, end, out_dir, db_url)] = code
        for future in as_completed(futures):
            code = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "code": code,
                    "success": False,
                    "error": str(exc),
                }

            if result.get("success"):
                completed_codes.add(code)
                completed_in_run += 1
                failed_codes.pop(code, None)
            else:
                failed_in_run += 1
                failed_codes[code] = str(result.get("error") or "抓取失败")

            _save_checkpoint(
                checkpoint_path,
                codes=codes,
                start=start,
                end=end,
                out_dir=out_dir,
                completed_codes=completed_codes,
                failed_codes=failed_codes,
            )
            maybe_emit_progress(code)

    maybe_emit_progress(None, force=True)

    if failed_codes:
        logger.error(
            "本轮抓取结束，但仍有 %d 只股票未成功抓取；已保留断点文件，可重新执行继续。",
            len(failed_codes),
        )
        return {
            "success": False,
            "total": total,
            "completed": len(completed_codes),
            "failed": len(failed_codes),
            "initial_completed": initial_completed,
            "checkpoint_path": str(checkpoint_path),
        }

    _clear_checkpoint(checkpoint_path)
    return {
        "success": True,
        "total": total,
        "completed": len(completed_codes),
        "failed": 0,
        "initial_completed": initial_completed,
        "checkpoint_path": str(checkpoint_path),
    }


# --------------------------- 增量更新 --------------------------- #
def _get_latest_date_from_csv(csv_path: Path) -> Optional[str]:
    """获取 CSV 文件中的最新日期"""
    try:
        df = pd.read_csv(csv_path)
        if "date" in df.columns and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            latest = df["date"].max()
            return latest.strftime("%Y%m%d")
    except Exception as e:
        logger.debug(f"读取 {csv_path} 失败: {e}")
    return None


def _classify_codes_by_local_csv(
    codes: List[str],
    out_dir: Path,
    end: str,
) -> tuple[list[str], list[str], list[str]]:
    """按本地 CSV 状态分类。

    ready_codes:
        CSV 已存在且最新日期已达到目标交易日。
    incremental_codes:
        CSV 存在且可读，但最新日期落后于目标交易日，只需补增量。
    full_codes:
        CSV 缺失或损坏，需要全量重抓。
    """
    ready_codes: list[str] = []
    incremental_codes: list[str] = []
    full_codes: list[str] = []

    for code in codes:
        csv_path = out_dir / f"{code}.csv"
        if not csv_path.exists():
            full_codes.append(code)
            continue

        latest_date = _get_latest_date_from_csv(csv_path)
        if not latest_date:
            full_codes.append(code)
            continue

        if latest_date >= end:
            ready_codes.append(code)
        else:
            incremental_codes.append(code)

    return ready_codes, incremental_codes, full_codes


def fetch_one_incremental(
    code: str,
    end: str,
    out_dir: Path,
    progress_callback: Optional[callable] = None,
    db_url: Optional[str] = None,
) -> dict:
    """增量更新单只股票

    Args:
        code: 股票代码
        end: 结束日期 (YYYYMMDD)
        out_dir: 输出目录
        progress_callback: 进度回调函数 callback(current, total, code)

    Returns:
        dict: 包含更新结果信息
    """
    csv_path = out_dir / f"{code}.csv"
    result = {
        "code": code,
        "success": False,
        "updated": False,
        "new_count": 0,
        "error": None,
    }

    # 检查现有文件
    latest_date = _get_latest_date_from_csv(csv_path)

    if latest_date:
        # 从最新日期的下一天开始抓取
        import datetime
        latest_dt = datetime.datetime.strptime(latest_date, "%Y%m%d")
        next_day = latest_dt + datetime.timedelta(days=1)
        start = next_day.strftime("%Y%m%d")
    else:
        # 文件不存在，使用默认起始日期
        start = "20190101"

    # 如果起始日期已经在结束日期之后，无需更新
    if start > end:
        result["success"] = True
        result["updated"] = False
        return result

    for attempt in range(1, 4):
        try:
            new_df = _get_kline_tushare(code, start, end)

            if new_df.empty:
                # 可能是停牌或无新数据
                result["success"] = True
                result["updated"] = False
                break

            new_df = validate(new_df)

            if latest_date and csv_path.exists():
                # 合并旧数据
                old_df = pd.read_csv(csv_path)
                old_df["date"] = pd.to_datetime(old_df["date"])
                combined_df = pd.concat([old_df, new_df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
                result["new_count"] = len(new_df)
            else:
                combined_df = new_df
                result["new_count"] = len(new_df)

            combined_df.to_csv(csv_path, index=False)
            # 增量模式只需要把新增交易日写入数据库，不要整份历史重复 upsert。
            if db_url:
                _save_to_db(code, new_df, db_url)
            result["success"] = True
            result["updated"] = True
            break
        except Exception as e:
            if _looks_like_ip_ban(e):
                logger.error(f"{code} 第 {attempt} 次抓取疑似被封禁，沉睡 {COOLDOWN_SECS} 秒")
                _cool_sleep(COOLDOWN_SECS)
            else:
                silent_seconds = 30 * attempt
                logger.info(f"{code} 第 {attempt} 次抓取失败，{silent_seconds} 秒后重试：{e}")
                time.sleep(silent_seconds)
    else:
        result["error"] = "三次抓取均失败"

    return result


def incremental_update(
    codes: List[str],
    end: Optional[str] = None,
    out_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    progress_callback: Optional[callable] = None,
    db_url: Optional[str] = None,
) -> dict:
    """增量更新多只股票

    Args:
        codes: 股票代码列表
        end: 结束日期 (YYYYMMDD)，默认为今天
        out_dir: 输出目录
        config_path: 配置文件路径
        progress_callback: 进度回调函数 callback(current, total, code, status)

    Returns:
        dict: 更新结果汇总
    """
    # 加载配置
    cfg_path = config_path or _CONFIG_PATH
    cfg = _load_config(cfg_path) if cfg_path.exists() else {}

    # 参数默认值
    if end is None:
        end = dt.date.today().strftime("%Y%m%d")
    if out_dir is None:
        out_dir = _resolve_cfg_path(cfg.get("out", "./data/raw"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # 确保 Tushare 已初始化
    global pro
    if pro is None:
        ts_token = _load_env_var("TUSHARE_TOKEN") or _load_env_var("TS_TOKEN")
        if not ts_token:
            raise ValueError("未找到 TUSHARE_TOKEN")
        pro = ts.pro_api(ts_token)

    workers = int(cfg.get("workers", 8))
    results = {
        "total": len(codes),
        "success": 0,
        "failed": 0,
        "updated": 0,
        "skipped": 0,
        "details": [],
    }

    def update_with_progress(code: str, index: int):
        result = fetch_one_incremental(code, end, out_dir, db_url=db_url)
        result["index"] = index
        results["details"].append(result)

        if result["success"]:
            results["success"] += 1
            if result["updated"]:
                results["updated"] += 1
            else:
                results["skipped"] += 1
        else:
            results["failed"] += 1

        # 回调进度
        if progress_callback:
            status = "updated" if result["updated"] else ("skipped" if result["success"] else "failed")
            progress_callback(index + 1, len(codes), code, status)

        return result

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(update_with_progress, code, i): code
            for i, code in enumerate(codes)
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"增量更新异常: {e}")

    return results



# --------------------------- 配置加载 --------------------------- #
_CONFIG_PATH = Path(__file__).parent.parent / "config" / "fetch_kline.yaml"

def _load_config(config_path: Path = _CONFIG_PATH) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    logger.info("已加载配置文件：%s", config_path.resolve())
    return cfg


# --------------------------- 主入口 --------------------------- #
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Tushare A股日线数据抓取")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config/fetch_kline.yaml）")
    parser.add_argument("--boards", nargs="+", default=None,
                        choices=["main", "gem", "star", "bj"],
                        help="指定抓取板块：main=主板, gem=创业板, star=科创板, bj=北交所（覆盖配置文件）")
    parser.add_argument("--log", default=None, help="日志文件路径")
    parser.add_argument("--incremental", action="store_true", help="增量更新模式（只更新新数据）")
    parser.add_argument("--db", action="store_true", help="将 K 线数据写入数据库（同时保留 CSV）")
    args = parser.parse_args()

    # ---------- 读取 YAML 配置 ---------- #
    cfg_path = Path(args.config) if args.config else _CONFIG_PATH
    cfg = _load_config(cfg_path)

    # ---------- 板块过滤：CLI 参数优先 ---------- #
    if args.boards is not None:
        include_boards = set(args.boards)
        exclude_boards = None
    else:
        include_boards = None
        exclude_boards = set(cfg.get("exclude_boards") or [])

    # ---------- 日志路径 ---------- #
    log_path = Path(args.log) if args.log else (
        _resolve_cfg_path(cfg.get("log")) if cfg.get("log") else _default_log_path()
    )
    setup_logging(log_path)
    logger.info("日志文件：%s", Path(log_path).resolve())

    # ---------- Tushare Token ---------- #
    os.environ["NO_PROXY"] = "api.waditu.com,.waditu.com,waditu.com"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    ts_token = _load_env_var("TUSHARE_TOKEN") or _load_env_var("TS_TOKEN")
    if not ts_token:
        raise ValueError("未找到 TUSHARE_TOKEN，请在环境变量或项目根目录 .env 中配置")
    global pro
    pro = ts.pro_api(ts_token)

    # ---------- 数据库写入（--db 模式） ---------- #
    db_url: Optional[str] = None
    if args.db:
        db_url = _load_env_var("DATABASE_URL")
        if not db_url:
            raise ValueError("未找到 DATABASE_URL，--db 模式需要 PostgreSQL 连接串")
        logger.info("已启用数据库写入模式，目标：%s", db_url)

    # ---------- 日期解析 ---------- #
    raw_start = str(cfg.get("start", "20190101"))
    raw_end   = str(cfg.get("end",   "today"))
    start = dt.date.today().strftime("%Y%m%d") if raw_start.lower() == "today" else raw_start
    end   = dt.date.today().strftime("%Y%m%d") if raw_end.lower()   == "today" else raw_end

    out_dir = _resolve_cfg_path(cfg.get("out", "./data"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 从 stocklist.csv 读取股票池 ---------- #
    stocklist_path = _resolve_cfg_path(cfg.get("stocklist", "./pipeline/stocklist.csv"))
    codes = load_codes_from_stocklist(stocklist_path, include_boards=include_boards, exclude_boards=exclude_boards)

    if not codes:
        logger.error("stocklist 为空或被过滤后无代码，请检查。")
        sys.exit(1)

    board_desc = ",".join(sorted(include_boards)) if include_boards else (",".join(sorted(exclude_boards)) if exclude_boards else "无")

    # ---------- 增量更新模式 ---------- #
    if args.incremental:
        logger.info(
            "开始增量更新 %d 支股票 | 数据源:Tushare(日线,qfq) | 结束日期:%s | 板块:%s | 限速:%d次/%d秒",
            len(codes), end, board_desc, MAX_REQUESTS_PER_WINDOW, WINDOW_SECONDS,
        )

        def progress_cb(current, total, code, status):
            logger.info(f"进度: {current}/{total} | {code} | {status}")

        results = incremental_update(codes, end=end, out_dir=out_dir, config_path=cfg_path, progress_callback=progress_cb, db_url=db_url)

        logger.info(
            "增量更新完成 | 成功:%d | 更新:%d | 跳过:%d | 失败:%d | 数据目录: %s",
            results["success"], results["updated"], results["skipped"], results["failed"],
            out_dir.resolve()
        )
        return

    # ---------- 全量抓取模式 ---------- #
    logger.info(
        "开始抓取 %d 支股票 | 数据源:Tushare(日线,qfq) | 日期:%s → %s | 板块:%s | 限速:%d次/%d秒",
        len(codes), start, end, board_desc, MAX_REQUESTS_PER_WINDOW, WINDOW_SECONDS,
    )

    workers = int(cfg.get("workers", 8))
    result = full_fetch(
        codes,
        start=start,
        end=end,
        out_dir=out_dir,
        workers=workers,
        db_url=db_url,
    )

    if not result["success"]:
        logger.error(
            "全量抓取未全部完成 | 已完成:%d/%d | 失败:%d | 断点文件:%s",
            result["completed"],
            result["total"],
            result["failed"],
            result["checkpoint_path"],
        )
        sys.exit(2)

    logger.info("全部任务完成，数据已保存至 %s", out_dir.resolve())


if __name__ == "__main__":
    main()
