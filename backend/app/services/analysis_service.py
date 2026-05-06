"""
Analysis Service
~~~~~~~~~~~~~~~~
股票分析服务，集成现有 Selector 和 quant_reviewer
优先使用数据库；测试和迁移场景下兼容 CSV 回退。
"""
import sys
from datetime import date as date_class, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd
import yaml
from sqlalchemy import and_

# 添加项目根目录到 Python 路径
ROOT = Path(__file__).parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.analysis_cache import analysis_cache
from app.services.kline_service import get_daily_data
from app.database import SessionLocal
from app.models import DailyB1Check, DailyB1CheckDetail


class AnalysisService:
    """股票分析服务"""

    # 策略版本，用于缓存失效
    STRATEGY_VERSION = analysis_cache.STRATEGY_VERSION
    HISTORY_WINDOW_DAYS = 180
    DETAIL_VERSION = "v1"

    def __init__(self):
        self._selector = None
        self._reviewer = None
        self._history_active_pool_cache: dict[tuple[str, str, int, int], dict[pd.Timestamp, set[str]]] = {}

    def load_stock_data(self, code: str, days: int = 365) -> Optional[pd.DataFrame]:
        """加载股票数据。

        Args:
            code: 股票代码
            days: 加载最近多少天的数据（默认365天）

        Returns:
            DataFrame with columns: date, open, close, high, low, volume
        """
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days * 2)  # 多取一些，过滤交易日

        with SessionLocal() as db:
            df = get_daily_data(db, code, start_date, end_date)

        if df is not None and not df.empty:
            # 标准化列名
            df.columns = [c.lower() for c in df.columns]

            # 确保 date 列存在
            if "date" not in df.columns:
                return None

            # 只取最近的 N 天数据
            df = df.tail(days).copy()
            return df.sort_values("date").reset_index(drop=True)

        return self._load_stock_data_from_csv(code, days)

    def _load_stock_data_from_csv(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """兼容旧数据目录结构，从 CSV 读取股票数据。"""
        raw_data_dir = Path(settings.raw_data_dir)
        candidate_dirs = []
        if raw_data_dir.is_absolute():
            candidate_dirs.append(raw_data_dir)
        else:
            candidate_dirs.append(ROOT / raw_data_dir)
        candidate_dirs.append(ROOT)

        csv_path = None
        for candidate_dir in candidate_dirs:
            path = candidate_dir / f"{code}.csv"
            if path.exists():
                csv_path = path
                break

        if csv_path is None:
            return None

        df = pd.read_csv(csv_path)
        if df.empty:
            return None

        # 标准化列名
        df.columns = [c.lower() for c in df.columns]

        # 确保 date 列存在
        if "date" not in df.columns:
            return None

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        if df.empty:
            return None

        # 只取最近的 N 天数据
        df = df.tail(days).copy()

        return df.sort_values("date").reset_index(drop=True)

    def _build_b1_selector(self):
        """构建与明日之星一致的 B1Selector 配置。"""
        pipeline_dir = ROOT / "pipeline"
        if str(pipeline_dir) not in sys.path:
            sys.path.insert(0, str(pipeline_dir))

        from Selector import B1Selector

        cfg = self._load_preselect_config()
        b1_cfg = cfg.get("b1", {})
        return B1Selector(
            j_threshold=float(b1_cfg.get("j_threshold", 15.0)),
            j_q_threshold=float(b1_cfg.get("j_q_threshold", 0.10)),
            zx_m1=int(b1_cfg.get("zx_m1", 14)),
            zx_m2=int(b1_cfg.get("zx_m2", 28)),
            zx_m3=int(b1_cfg.get("zx_m3", 57)),
            zx_m4=int(b1_cfg.get("zx_m4", 114)),
        )

    def _load_preselect_config(self) -> dict[str, Any]:
        """加载初选配置。"""
        config_file = ROOT / "config" / "rules_preselect.yaml"
        if not config_file.exists():
            return {}
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_quant_review_config(self) -> dict[str, Any]:
        """加载量化复核配置。"""
        agent_dir = ROOT / "agent"
        pipeline_dir = ROOT / "pipeline"
        if str(agent_dir) not in sys.path:
            sys.path.insert(0, str(agent_dir))
        if str(pipeline_dir) not in sys.path:
            sys.path.insert(0, str(pipeline_dir))

        from quant_reviewer import load_config

        return load_config()

    def _build_prefilter(self, config: Optional[dict[str, Any]] = None):
        """构建与明日之星一致的第 4 步前置过滤器。"""
        pipeline_dir = ROOT / "pipeline"
        if str(pipeline_dir) not in sys.path:
            sys.path.insert(0, str(pipeline_dir))

        from review_prefilter import Step4Prefilter

        return Step4Prefilter(config or self._load_quant_review_config())

    @staticmethod
    def _normalize_history_record(record: dict[str, Any]) -> dict[str, Any]:
        """兼容旧版历史文件，补齐新增字段。"""
        normalized = dict(record)
        normalized.setdefault("in_active_pool", None)
        normalized.setdefault("prefilter_passed", None)
        normalized.setdefault("tomorrow_star_pass", None)

        blocked_by = normalized.get("prefilter_blocked_by")
        if blocked_by is None:
            normalized["prefilter_blocked_by"] = None
        elif isinstance(blocked_by, list):
            normalized["prefilter_blocked_by"] = [str(item) for item in blocked_by]
        else:
            normalized["prefilter_blocked_by"] = [str(blocked_by)]

        return normalized

    @staticmethod
    def _derive_tomorrow_star_pass(
        *,
        in_active_pool: Optional[bool],
        b1_passed: Optional[bool],
        prefilter_passed: Optional[bool],
        verdict: Optional[str],
        signal_type: Optional[str],
    ) -> Optional[bool]:
        """派生单日是否满足明日之星主流程口径。"""
        if in_active_pool is None or prefilter_passed is None:
            return None
        return bool(
            in_active_pool
            and b1_passed
            and prefilter_passed
            and verdict == "PASS"
            and signal_type == "trend_start"
        )

    @staticmethod
    def _calculate_volume_health(df: pd.DataFrame) -> Optional[bool]:
        """基于最近成交量判断量能是否健康。"""
        vol_col = None
        if "volume" in df.columns:
            vol_col = "volume"
        elif "vol" in df.columns:
            vol_col = "vol"

        if not vol_col:
            return None

        recent_vol = df[vol_col].tail(5).mean()
        ma_vol = df[vol_col].tail(20).mean()
        if pd.notna(ma_vol) and ma_vol > 0:
            return bool(recent_vol >= ma_vol * 0.5)
        return None

    def _build_active_pool_sets(
        self,
        *,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
        preselect_cfg: dict[str, Any],
    ) -> dict[pd.Timestamp, set[str]]:
        """构建指定时间窗的流动性池成员集合。"""
        global_cfg = preselect_cfg.get("global", {})
        top_m = int(global_cfg.get("top_m", 2000))
        n_turnover_days = int(global_cfg.get("n_turnover_days", 43))
        cache_key = (
            start_ts.strftime("%Y-%m-%d"),
            end_ts.strftime("%Y-%m-%d"),
            top_m,
            n_turnover_days,
        )
        cached = self._history_active_pool_cache.get(cache_key)
        if cached is not None:
            return cached

        pipeline_dir = ROOT / "pipeline"
        if str(pipeline_dir) not in sys.path:
            sys.path.insert(0, str(pipeline_dir))

        from pipeline_core import MarketDataPreparer, TopTurnoverPoolBuilder
        from select_stock import load_raw_data

        raw_data = load_raw_data(str(ROOT / settings.raw_data_dir), end_date=end_ts.strftime("%Y-%m-%d"))
        preparer = MarketDataPreparer(
            start_date=start_ts,
            end_date=end_ts,
            warmup_bars=n_turnover_days,
            n_turnover_days=n_turnover_days,
            selector=None,
            n_jobs=4,
        )
        prepared = preparer.prepare_base_only(raw_data)
        pool_by_date = TopTurnoverPoolBuilder(top_m=top_m).build(prepared)
        pool_sets = {
            dt: set(codes)
            for dt, codes in pool_by_date.items()
            if start_ts <= dt <= end_ts
        }
        self._history_active_pool_cache[cache_key] = pool_sets
        return pool_sets

    def _normalize_pick_date(self, pick_date: Optional[str]) -> Optional[str]:
        """将日期统一规范为 YYYY-MM-DD。"""
        if not pick_date:
            return None
        pick_date = str(pick_date).strip()
        if len(pick_date) == 8 and pick_date.isdigit():
            return f"{pick_date[:4]}-{pick_date[4:6]}-{pick_date[6:]}"
        return pick_date

    @staticmethod
    def _normalize_check_date(check_date: Any) -> Optional[date_class]:
        if check_date is None:
            return None
        if isinstance(check_date, date_class) and not isinstance(check_date, datetime):
            return check_date
        try:
            ts = pd.Timestamp(check_date)
        except Exception:
            return None
        if pd.isna(ts):
            return None
        return ts.date()

    @staticmethod
    def _derive_fail_reason(
        *,
        in_active_pool: Optional[bool],
        b1_passed: Optional[bool],
        prefilter_passed: Optional[bool],
        prefilter_blocked_by: Optional[list[str]],
        verdict: Optional[str],
        signal_type: Optional[str],
    ) -> Optional[str]:
        if in_active_pool is False:
            return "未进入当日活跃池"
        if b1_passed is False:
            return "B1 规则未通过"
        if prefilter_passed is False:
            blocked = prefilter_blocked_by or []
            return f"前置过滤未通过: {', '.join(blocked)}" if blocked else "前置过滤未通过"
        if verdict != "PASS":
            if signal_type == "prefilter_blocked":
                return "量化复核被前置过滤拦截"
            return f"量化结论为 {verdict or 'FAIL'}"
        if signal_type != "trend_start":
            return f"信号类型为 {signal_type or '未知'}，不是 trend_start"
        return None

    def _build_history_detail_payload(
        self,
        *,
        record: dict[str, Any],
        score_result: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        fail_reason = self._derive_fail_reason(
            in_active_pool=record.get("in_active_pool"),
            b1_passed=record.get("b1_passed"),
            prefilter_passed=record.get("prefilter_passed"),
            prefilter_blocked_by=record.get("prefilter_blocked_by"),
            verdict=score_result.get("verdict"),
            signal_type=score_result.get("signal_type"),
        )
        return {
            "score_details_json": {
                "total_score": score_result.get("score"),
                "verdict": score_result.get("verdict"),
                "signal_type": score_result.get("signal_type"),
                "comment": score_result.get("comment"),
                "signal_reasoning": score_result.get("signal_reasoning"),
                "scores": score_result.get("scores") or {},
                "trend_reasoning": score_result.get("trend_reasoning"),
                "position_reasoning": score_result.get("position_reasoning"),
                "volume_reasoning": score_result.get("volume_reasoning"),
                "abnormal_move_reasoning": score_result.get("abnormal_move_reasoning"),
            },
            "rules_json": {
                "in_active_pool": record.get("in_active_pool"),
                "b1_passed": record.get("b1_passed"),
                "prefilter_passed": record.get("prefilter_passed"),
                "prefilter_blocked_by": record.get("prefilter_blocked_by"),
                "tomorrow_star_pass": record.get("tomorrow_star_pass"),
                "fail_reason": fail_reason,
            },
            "details_json": {
                "check_date": record.get("check_date"),
                "close_price": record.get("close_price"),
                "change_pct": record.get("change_pct"),
                "kdj_j": record.get("kdj_j"),
                "kdj_low_rank": record.get("kdj_low_rank"),
                "zx_long_pos": record.get("zx_long_pos"),
                "weekly_ma_aligned": record.get("weekly_ma_aligned"),
                "volume_healthy": record.get("volume_healthy"),
            },
        }

    def get_latest_candidate_date(self) -> Optional[str]:
        """读取最新候选日期（优先从数据库，回退到文件）。"""
        from app.services.candidate_service import get_candidate_service

        # 优先从数据库读取
        try:
            candidate_service = get_candidate_service()
            db_date = candidate_service.get_latest_candidate_date()
            if db_date:
                return db_date.isoformat()
        except Exception as e:
            import traceback
            traceback.print_exc()

        # 回退到文件读取
        import json
        latest_file = ROOT / settings.candidates_dir / "candidates_latest.json"
        if not latest_file.exists():
            return None
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return self._normalize_pick_date(data.get("pick_date"))
        except Exception:
            return None

    def get_latest_result_date(self) -> Optional[str]:
        """读取最新分析结果日期。"""
        review_dir = ROOT / settings.review_dir
        if not review_dir.exists():
            return None
        date_dirs = [
            d.name for d in review_dir.iterdir()
            if d.is_dir() and (d / "suggestion.json").exists()
        ]
        return max(date_dirs) if date_dirs else None

    def load_candidate_codes(self, pick_date: Optional[str] = None) -> tuple[Optional[str], list[str]]:
        """读取指定日期的候选代码（优先从数据库，回退到文件）。

        Args:
            pick_date: 选拔日期 (YYYY-MM-DD)，None 表示读取最新

        Returns:
            (pick_date, codes) 元组
        """
        from app.services.candidate_service import get_candidate_service

        normalized_date = self._normalize_pick_date(pick_date)

        # 优先从数据库读取
        try:
            candidate_service = get_candidate_service()
            db_date, candidates = candidate_service.load_candidates(pick_date, limit=1000)
            if candidates:
                codes = [c.get("code", "") for c in candidates if c.get("code")]
                return db_date or normalized_date, codes
        except Exception as e:
            import traceback
            traceback.print_exc()

        # 回退到文件读取
        import json
        candidates_dir = ROOT / settings.candidates_dir
        if normalized_date:
            candidate_file = candidates_dir / f"candidates_{normalized_date}.json"
        else:
            candidate_file = candidates_dir / "candidates_latest.json"

        if not candidate_file.exists():
            return normalized_date, []

        try:
            with open(candidate_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            file_pick_date = self._normalize_pick_date(data.get("pick_date")) or normalized_date
            codes = [item.get("code", "") for item in data.get("candidates", []) if item.get("code")]
            return file_pick_date, codes
        except Exception:
            return normalized_date, []

    def check_b1_strategy(self, code: str) -> Dict[str, Any]:
        """执行 B1 策略检查"""
        df = self.load_stock_data(code)
        if df is None or df.empty:
            return {
                "code": code,
                "b1_passed": False,
                "kdj_j": None,
                "zx_long_pos": None,
                "weekly_ma_aligned": None,
                "volume_healthy": None,
                "error": "数据不存在"
            }

        selector = self._build_b1_selector()
        try:
            # 使用 prepare_df 预计算所有指标
            df_prepared = selector.prepare_df(df)

            # 获取最后一行的数据
            last_row = df_prepared.iloc[-1]

            # 从 _vec_pick 列判断是否通过 B1 策略
            b1_passed = bool(last_row.get("_vec_pick", False))

            # 获取各项指标值
            kdj_j = None
            if "J" in last_row and pd.notna(last_row["J"]):
                kdj_j = float(last_row["J"])

            zx_long_pos = None
            if "zxdq" in last_row and "zxdkx" in last_row:
                zx_long_pos = bool(last_row["zxdq"] > last_row["zxdkx"])

            weekly_ma_aligned = None
            if "wma_bull" in last_row and pd.notna(last_row["wma_bull"]):
                weekly_ma_aligned = bool(last_row["wma_bull"])

            volume_healthy = self._calculate_volume_health(df_prepared)

            # 获取日期
            check_date = None
            if "date" in last_row:
                date_val = last_row["date"]
                if isinstance(date_val, pd.Timestamp):
                    check_date = date_val.strftime("%Y-%m-%d")
                else:
                    check_date = str(date_val)

            # 获取收盘价
            close_price = None
            if "close" in last_row and pd.notna(last_row["close"]):
                close_price = float(last_row["close"])

            return {
                "code": code,
                "b1_passed": b1_passed,
                "kdj_j": kdj_j,
                "kdj_low_rank": None,
                "zx_long_pos": zx_long_pos,
                "weekly_ma_aligned": weekly_ma_aligned,
                "volume_healthy": volume_healthy,
                "close_price": close_price,
                "check_date": check_date,
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "code": code,
                "b1_passed": False,
                "kdj_j": None,
                "zx_long_pos": None,
                "weekly_ma_aligned": None,
                "volume_healthy": None,
                "error": str(e)
            }

    def analyze_stock(
        self,
        code: str,
        reviewer: str = "quant",
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        执行完整的单股分析

        Args:
            code: 股票代码
            reviewer: 评审者类型 (quant/glm/qwen/gemini)
            use_cache: 是否使用缓存（默认 True）

        Returns:
            分析结果字典，包含缓存状态标识 _cached
        """
        import json

        # 先执行 B1 检查以确定交易日
        b1_result = self.check_b1_strategy(code)
        analysis_date = (
            self._normalize_pick_date(b1_result.get("check_date"))
            or self._normalize_pick_date(b1_result.get("analysis_date"))
            or datetime.now().strftime("%Y-%m-%d")
        )

        # 检查缓存
        if use_cache:
            cache_key = analysis_cache.make_cache_key(code, analysis_date, self.STRATEGY_VERSION)
            cached_result = analysis_cache.get_cached_analysis(code, analysis_date)

            if cached_result is not None:
                # 规范化缓存结果，确保与实时计算返回结构一致
                # 缓存文件使用 total_score，运行时使用 score，需要统一
                # 注意：使用 'is not None' 检查以支持 score 为 0 的有效值
                cached_score = cached_result.get("score")
                cached_total_score = cached_result.get("total_score")
                normalized_score = cached_score if cached_score is not None else cached_total_score

                normalized = {
                    "code": cached_result.get("code", code),
                    "score": normalized_score,
                    "verdict": cached_result.get("verdict"),
                    "comment": cached_result.get("comment"),
                    "signal_type": cached_result.get("signal_type"),
                    "b1_passed": cached_result.get("b1_passed", b1_result.get("b1_passed")),
                    "kdj_j": cached_result.get("kdj_j", b1_result.get("kdj_j")),
                    "zx_long_pos": cached_result.get("zx_long_pos", b1_result.get("zx_long_pos")),
                    "weekly_ma_aligned": cached_result.get("weekly_ma_aligned", b1_result.get("weekly_ma_aligned")),
                    "volume_healthy": cached_result.get("volume_healthy", b1_result.get("volume_healthy")),
                    "close_price": cached_result.get("close_price", b1_result.get("close_price")),
                    "analysis_date": cached_result.get("analysis_date") or cached_result.get("pick_date") or analysis_date,
                    # 保留原始 total_score 以兼容现有代码
                    "total_score": cached_total_score if cached_total_score is not None else cached_score,
                    # 保留其他可能存在的字段
                    "scores": cached_result.get("scores"),
                    "trend_reasoning": cached_result.get("trend_reasoning"),
                    "position_reasoning": cached_result.get("position_reasoning"),
                    "volume_reasoning": cached_result.get("volume_reasoning"),
                    "abnormal_move_reasoning": cached_result.get("abnormal_move_reasoning"),
                    "signal_reasoning": cached_result.get("signal_reasoning"),
                    # 内部状态字段
                    "_cached": True,
                    "_cache_key": cache_key,
                }
                return normalized

            # 检查是否正在进行
            if analysis_cache.is_analysis_in_progress(cache_key):
                # 返回"分析中"状态
                return {
                    "code": code,
                    "b1_passed": b1_result.get("b1_passed", False),
                    "check_date": analysis_date,
                    "_status": "analyzing",
                    "_cache_key": cache_key,
                }

            # 尝试获取分析锁
            acquired, lock = analysis_cache.start_analysis(cache_key)
            if not acquired:
                # 其他请求正在分析，返回等待状态
                return {
                    "code": code,
                    "b1_passed": b1_result.get("b1_passed", False),
                    "check_date": analysis_date,
                    "_status": "waiting",
                    "_cache_key": cache_key,
                }

        try:
            result = {
                "code": code,
                **b1_result
            }

            # 执行评分
            if reviewer == "quant":
                score_result = self._quant_review(code)
                result.update(score_result)
                # 同时设置 total_score 以保持与缓存结构一致
                if "score" in result:
                    result["total_score"] = result["score"]
            else:
                # TODO: 调用 LLM 评分
                result["score"] = None
                result["total_score"] = None
                result["verdict"] = "UNKNOWN"
                result["comment"] = "LLM 评分待实现"

            # 保存分析结果到文件（供历史记录读取）
            if result.get("score") is not None:
                try:
                    # 尝试获取股票的收盘价（用于历史记录显示）
                    close_price = result.get("close_price")
                    if close_price is None:
                        df = self.load_stock_data(code)
                        if df is not None and not df.empty:
                            close_price = float(df.iloc[-1]["close"])

                    # 准备保存数据
                    save_data = {
                        "code": code,
                        "total_score": result.get("score"),
                        "verdict": result.get("verdict"),
                        "signal_type": result.get("signal_type"),
                        "signal_reasoning": result.get("signal_reasoning"),
                        "comment": result.get("comment"),
                        "trend_reasoning": result.get("trend_reasoning"),
                        "position_reasoning": result.get("position_reasoning"),
                        "volume_reasoning": result.get("volume_reasoning"),
                        "abnormal_move_reasoning": result.get("abnormal_move_reasoning"),
                        "scores": result.get("scores"),
                        "b1_passed": result.get("b1_passed"),
                        "kdj_j": result.get("kdj_j"),
                        "zx_long_pos": result.get("zx_long_pos"),
                        "weekly_ma_aligned": result.get("weekly_ma_aligned"),
                        "volume_healthy": result.get("volume_healthy"),
                        "close_price": close_price,
                        "analysis_date": analysis_date,
                        "pick_date": analysis_date,
                    }

                    # 使用缓存服务保存
                    analysis_cache.save_analysis_result(code, analysis_date, save_data)

                    # 更新结果
                    result["close_price"] = close_price
                except Exception as e:
                    # 保存失败不影响主流程
                    import traceback
                    traceback.print_exc()

            # 标记为非缓存结果
            result["_cached"] = False

            # 确保 analysis_date 字段存在（与缓存路径保持一致）
            if "analysis_date" not in result:
                result["analysis_date"] = analysis_date

            return result

        finally:
            # 释放锁（如果已获取）
            if use_cache:
                cache_key = analysis_cache.make_cache_key(code, analysis_date, self.STRATEGY_VERSION)
                # 注意：这里不调用 finish_analysis，因为结果在上面已经保存
                # 只需要确保锁被释放
                with analysis_cache._global_lock:
                    if cache_key in analysis_cache._in_progress:
                        lock = analysis_cache._in_progress.pop(cache_key)
                        if lock:
                            try:
                                lock.release()
                            except RuntimeError:
                                pass

    def _quant_review(self, code: str) -> Dict[str, Any]:
        """量化评分"""
        # 添加 agent 和 pipeline 目录到 Python 路径
        agent_dir = ROOT / "agent"
        pipeline_dir = ROOT / "pipeline"
        if str(agent_dir) not in sys.path:
            sys.path.insert(0, str(agent_dir))
        if str(pipeline_dir) not in sys.path:
            sys.path.insert(0, str(pipeline_dir))

        from quant_reviewer import QuantReviewer, load_config

        df = self.load_stock_data(code)
        if df is None or df.empty:
            return {
                "score": 0,
                "verdict": "FAIL",
                "comment": "数据不存在"
            }

        try:
            # 加载配置并创建 reviewer
            config = load_config()
            reviewer = QuantReviewer(config)

            # 调用量化评分 - 使用 review_stock_df 避免重复加载数据
            result = reviewer.review_stock_df(code, df)

            return {
                "score": result.get("total_score", 0),
                "verdict": result.get("verdict", "FAIL"),
                "comment": result.get("comment", ""),
                "signal_type": result.get("signal_type", ""),
                # 返回详细的评分信息
                "scores": result.get("scores", {}),
                "trend_reasoning": result.get("trend_reasoning", ""),
                "position_reasoning": result.get("position_reasoning", ""),
                "volume_reasoning": result.get("volume_reasoning", ""),
                "abnormal_move_reasoning": result.get("abnormal_move_reasoning", ""),
                "signal_reasoning": result.get("signal_reasoning", ""),
            }
        except FileNotFoundError as e:
            return {
                "score": 0,
                "verdict": "FAIL",
                "comment": f"配置文件或数据文件不存在: {str(e)}"
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "score": 0,
                "verdict": "FAIL",
                "comment": f"评分失败: {str(e)}"
            }

    def get_candidates_history(self, limit: int = 30) -> list:
        """获取候选历史（优先从数据库，回退到文件）"""
        from app.services.candidate_service import get_candidate_service

        # 优先从数据库读取
        try:
            candidate_service = get_candidate_service()
            db_history = candidate_service.get_candidate_dates(limit)
            if db_history:
                return db_history
        except Exception as e:
            import traceback
            traceback.print_exc()

        # 回退到文件读取
        import json
        candidates_dir = ROOT / settings.candidates_dir
        review_dir = ROOT / settings.review_dir
        history_by_date: dict[str, dict[str, Any]] = {}

        # 读取所有历史文件
        for file in sorted(candidates_dir.glob("candidates_*.json"), reverse=True)[:limit]:
            if file.name == "candidates_latest.json":
                continue
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    pick_date = self._normalize_pick_date(data.get("pick_date", file.stem.split("_")[-1]))
                    if not pick_date:
                        continue
                    pass_count = 0

                    suggestion_file = review_dir / str(pick_date) / "suggestion.json"
                    if suggestion_file.exists():
                        try:
                            with open(suggestion_file, "r", encoding="utf-8") as sf:
                                suggestion_data = json.load(sf)
                            recommendations = suggestion_data.get("recommendations", [])
                            pass_count = sum(1 for item in recommendations if item.get("verdict") == "PASS")
                        except Exception:
                            pass_count = 0

                    history_by_date[pick_date] = {
                        "date": pick_date,
                        "count": len(data.get("candidates", [])),
                        "pass": pass_count,
                        "file": str(file)
                    }
            except:
                pass

        history = sorted(history_by_date.values(), key=lambda item: item["date"], reverse=True)
        return history[:limit]

    def get_analysis_results(self, pick_date: Optional[str] = None) -> Dict[str, Any]:
        """获取分析结果（仅读模式，不触发任何写入操作）

        仅返回已存在的分析结果，不执行评分，不保存文件。
        如需重建 suggestion.json，请使用后台任务或离线脚本。
        """
        import json
        pick_date = self._normalize_pick_date(pick_date)

        if not pick_date:
            # 获取最新日期
            pick_date = self.get_latest_candidate_date()

        if not pick_date:
            return {"pick_date": None, "results": [], "total": 0, "min_score_threshold": 4.0}

        suggestion_file = ROOT / settings.review_dir / pick_date / "suggestion.json"
        review_dir = ROOT / settings.review_dir / pick_date
        _, candidate_codes_list = self.load_candidate_codes(pick_date)
        candidate_codes = set(candidate_codes_list)

        # 仅读模式：不创建目录，不写入文件

        try:
            detailed_results = []
            missing_analysis_codes = []

            if candidate_codes_list:
                for code in candidate_codes_list:
                    stock_file = review_dir / f"{code}.json"
                    if not stock_file.exists():
                        missing_analysis_codes.append(code)
                        continue
                    with open(stock_file, "r", encoding="utf-8") as f:
                        item = json.load(f)
                    detailed_results.append({
                        "code": item.get("code", code),
                        "verdict": item.get("verdict"),
                        "total_score": item.get("total_score", item.get("score")),
                        "signal_type": item.get("signal_type"),
                        "comment": item.get("comment"),
                    })

            # 仅读模式：记录缺失但不触发补算
            if missing_analysis_codes:
                print(f"[get_analysis_results] 检测到 {len(missing_analysis_codes)} 个候选股票缺少分析结果（仅读模式，不触发补算）")

            if detailed_results:
                # 按 verdict 优先级和 score 排序，生成 Top 5
                verdict_priority = {"PASS": 3, "WATCH": 2, "FAIL": 1, "": 0}
                sorted_results = sorted(
                    detailed_results,
                    key=lambda x: (
                        verdict_priority.get(x.get("verdict", ""), 0),
                        x.get("total_score", 0) or 0
                    ),
                    reverse=True
                )

                # 仅读模式：不保存 suggestion.json
                # suggestion.json 的重建应由后台任务或离线脚本完成

                return {
                    "pick_date": pick_date,
                    "results": sorted_results,  # 返回所有结果
                    "total": len(sorted_results),
                    "min_score_threshold": settings.min_score_threshold,
                }

            # 如果没有从个股文件获取到结果，尝试从 suggestion.json 读取
            if not suggestion_file.exists():
                return {"pick_date": pick_date, "results": [], "total": 0, "min_score_threshold": 4.0}

            with open(suggestion_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            recommendations = data.get("recommendations", [])
            if candidate_codes:
                recommendations = [
                    item for item in recommendations
                    if item.get("code") in candidate_codes
                ]
            return {
                "pick_date": pick_date,
                "results": recommendations,
                "total": len(recommendations),
                "min_score_threshold": data.get("min_score_threshold", 4.0)
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"pick_date": pick_date, "results": [], "total": 0, "min_score_threshold": 4.0}

    def get_stock_history_checks(
        self,
        code: str,
        days: int = 180,
        page: int = 1,
        page_size: int | None = None,
    ) -> tuple[list, int]:
        """获取股票历史检查记录（数据库持久化）。"""
        days = max(1, min(int(days), self.HISTORY_WINDOW_DAYS))
        page = max(1, int(page))
        if page_size is not None:
            page_size = max(1, min(int(page_size), days))
        code = code.zfill(6)
        with SessionLocal() as db:
            base_query = (
                db.query(DailyB1Check, DailyB1CheckDetail)
                .outerjoin(
                    DailyB1CheckDetail,
                    and_(
                        DailyB1CheckDetail.code == DailyB1Check.code,
                        DailyB1CheckDetail.check_date == DailyB1Check.check_date,
                    ),
                )
                .filter(DailyB1Check.code == code)
                .order_by(DailyB1Check.check_date.desc(), DailyB1Check.id.desc())
            )
            total = min(base_query.count(), days)
            query = base_query.limit(days)
            if page_size is not None:
                offset = (page - 1) * page_size
                query = query.offset(offset).limit(page_size)
            rows = query.all()
            history = []
            for item, detail in rows:
                score_details = detail.score_details_json if detail else {}
                rules = detail.rules_json if detail else {}
                history.append(self._normalize_history_record({
                    "check_date": item.check_date.isoformat(),
                    "close_price": item.close_price,
                    "change_pct": item.change_pct,
                    "kdj_j": item.kdj_j,
                    "kdj_low_rank": item.kdj_low_rank,
                    "zx_long_pos": item.zx_long_pos,
                    "weekly_ma_aligned": item.weekly_ma_aligned,
                    "volume_healthy": item.volume_healthy,
                    "in_active_pool": rules.get("in_active_pool"),
                    "b1_passed": item.b1_passed,
                    "prefilter_passed": rules.get("prefilter_passed"),
                    "prefilter_blocked_by": rules.get("prefilter_blocked_by"),
                    "score": item.score,
                    "verdict": score_details.get("verdict"),
                    "signal_type": score_details.get("signal_type"),
                    "tomorrow_star_pass": rules.get("tomorrow_star_pass"),
                    "notes": item.notes,
                    "detail_ready": bool(detail and detail.status == "ready"),
                    "detail_version": detail.detail_version if detail else None,
                    "detail_updated_at": detail.updated_at if detail else None,
                }))
            return history, total

    def generate_stock_history_checks(self, code: str, days: int = 180, clean: bool = True) -> dict:
        """
        重新刷新并持久化股票历史检查数据

        为每个交易日生成收盘后的完整检查数据（包括B1检查、评分、信号），
        并写入 daily_b1_checks / daily_b1_check_details。

        Args:
            code: 股票代码
            days: 生成最近N个交易日的历史数据
            clean: 是否先清理旧数据
        """
        df = self.load_stock_data(code)
        if df is None or df.empty:
            return {"success": False, "error": "数据不存在"}

        # 计算涨跌幅（如果不存在）
        if "change_pct" not in df.columns:
            df["change_pct"] = df["close"].pct_change() * 100

        selector = self._build_b1_selector()
        quant_config = self._load_quant_review_config()
        prefilter = self._build_prefilter(quant_config)
        preselect_cfg = self._load_preselect_config()

        days = max(1, min(int(days), self.HISTORY_WINDOW_DAYS))
        recent_df = df.tail(days).copy()
        target_dates = [pd.Timestamp(ts).normalize() for ts in recent_df["date"].tolist()]
        active_pool_sets = self._build_active_pool_sets(
            start_ts=min(target_dates),
            end_ts=max(target_dates),
            preselect_cfg=preselect_cfg,
        ) if target_dates else {}

        generated_count = 0
        keep_dates: list[date_class] = []
        with SessionLocal() as db:
            if clean:
                db.query(DailyB1CheckDetail).filter(DailyB1CheckDetail.code == code).delete()
                db.query(DailyB1Check).filter(DailyB1Check.code == code).delete()
                db.commit()

            for _, row in recent_df.iterrows():
                check_date = row["date"].strftime("%Y-%m-%d")
                check_date_obj = date_class.fromisoformat(check_date)
                df_before = df[df["date"] <= row["date"]].copy()
                if len(df_before) < 60:
                    continue
                try:
                    df_prepared = selector.prepare_df(df_before)
                    last_row = df_prepared.iloc[-1]
                    change_pct = row.get("change_pct")
                    if pd.isna(change_pct):
                        change_pct = None
                    elif isinstance(change_pct, (int, float)):
                        change_pct = float(change_pct)
                    else:
                        change_pct = None

                    b1_passed = bool(last_row["_vec_pick"]) if pd.notna(last_row.get("_vec_pick")) else False
                    kdj_j = float(last_row["J"]) if pd.notna(last_row.get("J")) else None
                    zx_long_pos = bool(last_row["zxdq"] > last_row["zxdkx"]) if pd.notna(last_row.get("zxdq")) and pd.notna(last_row.get("zxdkx")) else None
                    weekly_ma_aligned = bool(last_row["wma_bull"]) if pd.notna(last_row.get("wma_bull")) else None
                    in_active_pool = code in active_pool_sets.get(pd.Timestamp(row["date"]).normalize(), set())

                    prefilter_passed: Optional[bool] = None
                    prefilter_blocked_by: Optional[list[str]] = None
                    try:
                        prefilter_result = prefilter.evaluate(code=code, pick_date=check_date, price_df=df_before)
                        prefilter_passed = bool(prefilter_result.get("passed", True))
                        prefilter_blocked_by = [str(item) for item in prefilter_result.get("blocked_by", [])]
                    except Exception:
                        import traceback
                        traceback.print_exc()

                    score_result = self._quant_review_for_date(code, df_before, check_date, config=quant_config)
                    tomorrow_star_pass = self._derive_tomorrow_star_pass(
                        in_active_pool=in_active_pool,
                        b1_passed=b1_passed,
                        prefilter_passed=prefilter_passed,
                        verdict=score_result.get("verdict"),
                        signal_type=score_result.get("signal_type"),
                    )
                    fail_reason = self._derive_fail_reason(
                        in_active_pool=in_active_pool,
                        b1_passed=b1_passed,
                        prefilter_passed=prefilter_passed,
                        prefilter_blocked_by=prefilter_blocked_by,
                        verdict=score_result.get("verdict"),
                        signal_type=score_result.get("signal_type"),
                    )
                    record = {
                        "check_date": check_date,
                        "close_price": float(row["close"]) if pd.notna(row.get("close")) else None,
                        "change_pct": change_pct,
                        "kdj_j": kdj_j,
                        "kdj_low_rank": None,
                        "zx_long_pos": zx_long_pos,
                        "weekly_ma_aligned": weekly_ma_aligned,
                        "volume_healthy": self._calculate_volume_health(df_prepared),
                        "in_active_pool": in_active_pool,
                        "b1_passed": b1_passed,
                        "prefilter_passed": prefilter_passed,
                        "prefilter_blocked_by": prefilter_blocked_by,
                        "score": score_result.get("score"),
                        "verdict": score_result.get("verdict"),
                        "signal_type": score_result.get("signal_type"),
                        "tomorrow_star_pass": tomorrow_star_pass,
                        "notes": fail_reason,
                    }
                    detail_payload = self._build_history_detail_payload(record=record, score_result=score_result)
                    existing_check = (
                        db.query(DailyB1Check)
                        .filter(DailyB1Check.code == code, DailyB1Check.check_date == check_date_obj)
                        .first()
                    )
                    if existing_check is None:
                        existing_check = DailyB1Check(code=code, check_date=check_date_obj)
                        db.add(existing_check)
                    existing_check.close_price = record["close_price"]
                    existing_check.change_pct = record["change_pct"]
                    existing_check.kdj_j = record["kdj_j"]
                    existing_check.kdj_low_rank = record["kdj_low_rank"]
                    existing_check.zx_long_pos = record["zx_long_pos"]
                    existing_check.weekly_ma_aligned = record["weekly_ma_aligned"]
                    existing_check.volume_healthy = record["volume_healthy"]
                    existing_check.b1_passed = record["b1_passed"]
                    existing_check.score = record["score"]
                    existing_check.notes = record["notes"]

                    existing_detail = (
                        db.query(DailyB1CheckDetail)
                        .filter(DailyB1CheckDetail.code == code, DailyB1CheckDetail.check_date == check_date_obj)
                        .first()
                    )
                    if existing_detail is None:
                        existing_detail = DailyB1CheckDetail(code=code, check_date=check_date_obj)
                        db.add(existing_detail)
                    existing_detail.status = "ready"
                    existing_detail.detail_version = self.DETAIL_VERSION
                    existing_detail.strategy_version = self.STRATEGY_VERSION
                    existing_detail.rule_version = self.DETAIL_VERSION
                    existing_detail.score_details_json = detail_payload["score_details_json"]
                    existing_detail.rules_json = detail_payload["rules_json"]
                    existing_detail.details_json = detail_payload["details_json"]
                    keep_dates.append(check_date_obj)
                    generated_count += 1
                    if generated_count % 20 == 0:
                        db.commit()
                except Exception:
                    import traceback
                    traceback.print_exc()
                    continue

            db.commit()
            if keep_dates:
                db.query(DailyB1CheckDetail).filter(
                    DailyB1CheckDetail.code == code,
                    ~DailyB1CheckDetail.check_date.in_(keep_dates),
                ).delete(synchronize_session=False)
                db.query(DailyB1Check).filter(
                    DailyB1Check.code == code,
                    ~DailyB1Check.check_date.in_(keep_dates),
                ).delete(synchronize_session=False)
                db.commit()

        return {
            "success": True,
            "code": code,
            "generated_count": generated_count,
            "days": days,
        }

    def get_history_detail(self, code: str, check_date: Any) -> Optional[dict[str, Any]]:
        code = code.zfill(6)
        check_date_obj = self._normalize_check_date(check_date)
        if not check_date_obj:
            return None
        with SessionLocal() as db:
            detail = (
                db.query(DailyB1CheckDetail)
                .filter(
                    DailyB1CheckDetail.code == code,
                    DailyB1CheckDetail.check_date == check_date_obj,
                )
                .first()
            )
            if detail is None:
                return None
            return {
                "code": code,
                "check_date": check_date_obj,
                "status": detail.status,
                "detail_ready": detail.status == "ready",
                "detail_version": detail.detail_version,
                "strategy_version": detail.strategy_version,
                "rule_version": detail.rule_version,
                "detail_updated_at": detail.updated_at,
                "payload": {
                    "score_details": detail.score_details_json,
                    "rules": detail.rules_json,
                    "details": detail.details_json,
                },
            }

    def generate_history_detail(self, code: str, check_date: Any, force: bool = False) -> dict[str, Any]:
        code = code.zfill(6)
        check_date_obj = self._normalize_check_date(check_date)
        if not check_date_obj:
            return {"success": False, "error": "无效的交易日"}

        existing = self.get_history_detail(code, check_date_obj)
        if existing and existing.get("detail_ready") and not force:
            return {"success": True, "code": code, "check_date": check_date_obj.isoformat(), "reused": True}

        df = self.load_stock_data(code, days=365)
        if df is None or df.empty:
            return {"success": False, "error": "数据不存在"}

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        target_ts = pd.Timestamp(check_date_obj)
        df_before = df[df["date"] <= target_ts].copy()
        if len(df_before) < 60:
            return {"success": False, "error": "历史数据不足，无法生成详情"}

        selector = self._build_b1_selector()
        quant_config = self._load_quant_review_config()
        prefilter = self._build_prefilter(quant_config)
        preselect_cfg = self._load_preselect_config()
        active_pool_sets = self._build_active_pool_sets(
            start_ts=target_ts.normalize(),
            end_ts=target_ts.normalize(),
            preselect_cfg=preselect_cfg,
        )

        df_prepared = selector.prepare_df(df_before)
        last_row = df_prepared.iloc[-1]
        score_result = self._quant_review_for_date(code, df_before, check_date_obj.isoformat(), config=quant_config)
        prefilter_result = prefilter.evaluate(code=code, pick_date=check_date_obj.isoformat(), price_df=df_before)
        prefilter_passed = bool(prefilter_result.get("passed", True))
        prefilter_blocked_by = [str(item) for item in prefilter_result.get("blocked_by", [])]
        in_active_pool = code in active_pool_sets.get(target_ts.normalize(), set())
        b1_passed = bool(last_row["_vec_pick"]) if pd.notna(last_row.get("_vec_pick")) else False
        record = {
            "check_date": check_date_obj.isoformat(),
            "close_price": float(last_row["close"]) if pd.notna(last_row.get("close")) else None,
            "change_pct": float(df_before["close"].pct_change().iloc[-1] * 100) if len(df_before) >= 2 and pd.notna(df_before["close"].pct_change().iloc[-1]) else None,
            "kdj_j": float(last_row["J"]) if pd.notna(last_row.get("J")) else None,
            "kdj_low_rank": None,
            "zx_long_pos": bool(last_row["zxdq"] > last_row["zxdkx"]) if pd.notna(last_row.get("zxdq")) and pd.notna(last_row.get("zxdkx")) else None,
            "weekly_ma_aligned": bool(last_row["wma_bull"]) if pd.notna(last_row.get("wma_bull")) else None,
            "volume_healthy": self._calculate_volume_health(df_prepared),
            "in_active_pool": in_active_pool,
            "b1_passed": b1_passed,
            "prefilter_passed": prefilter_passed,
            "prefilter_blocked_by": prefilter_blocked_by,
            "score": score_result.get("score"),
            "verdict": score_result.get("verdict"),
            "signal_type": score_result.get("signal_type"),
            "tomorrow_star_pass": self._derive_tomorrow_star_pass(
                in_active_pool=in_active_pool,
                b1_passed=b1_passed,
                prefilter_passed=prefilter_passed,
                verdict=score_result.get("verdict"),
                signal_type=score_result.get("signal_type"),
            ),
        }
        payload = self._build_history_detail_payload(record=record, score_result=score_result)
        with SessionLocal() as db:
            detail = (
                db.query(DailyB1CheckDetail)
                .filter(
                    DailyB1CheckDetail.code == code,
                    DailyB1CheckDetail.check_date == check_date_obj,
                )
                .first()
            )
            if detail is None:
                detail = DailyB1CheckDetail(code=code, check_date=check_date_obj)
                db.add(detail)
            detail.status = "ready"
            detail.detail_version = self.DETAIL_VERSION
            detail.strategy_version = self.STRATEGY_VERSION
            detail.rule_version = self.DETAIL_VERSION
            detail.score_details_json = payload["score_details_json"]
            detail.rules_json = payload["rules_json"]
            detail.details_json = payload["details_json"]
            db.commit()
        return {"success": True, "code": code, "check_date": check_date_obj.isoformat()}

    def _quant_review_for_date(
        self,
        code: str,
        df: pd.DataFrame,
        check_date: str = None,
        config: Optional[dict[str, Any]] = None,
    ) -> dict:
        """针对特定日期的数据进行量化评分

        注意：此方法用于历史数据生成，会绕过 prefilter 检查。

        Args:
            code: 股票代码
            df: 股票数据DataFrame（该日期之前的所有数据）
            check_date: 检查日期（YYYY-MM-DD格式），用于指定评分的截止日期
        """
        if df is None or df.empty:
            return {
                "score": None,
                "verdict": "FAIL",
                "signal_type": None,
            }

        try:
            # 添加 agent 和 pipeline 目录到 Python 路径
            agent_dir = ROOT / "agent"
            pipeline_dir = ROOT / "pipeline"
            if str(agent_dir) not in sys.path:
                sys.path.insert(0, str(agent_dir))
            if str(pipeline_dir) not in sys.path:
                sys.path.insert(0, str(pipeline_dir))

            from quant_reviewer import prepare_review_frame, review_prepared_frame

            # 加载配置
            review_config = config or self._load_quant_review_config()

            # 直接调用评分逻辑，绕过 prefilter
            frame = prepare_review_frame(df, review_config)
            result = review_prepared_frame(frame, review_config, code=code, asof_date=check_date, strategy=None)

            return {
                "score": result.get("total_score"),
                "verdict": result.get("verdict", "FAIL"),
                "signal_type": result.get("signal_type"),
                "comment": result.get("comment"),
                "signal_reasoning": result.get("signal_reasoning"),
                "scores": result.get("scores", {}),
                "trend_reasoning": result.get("trend_reasoning"),
                "position_reasoning": result.get("position_reasoning"),
                "volume_reasoning": result.get("volume_reasoning"),
                "abnormal_move_reasoning": result.get("abnormal_move_reasoning"),
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "score": None,
                "verdict": "FAIL",
                "signal_type": None,
                "comment": None,
                "signal_reasoning": None,
                "scores": {},
                "trend_reasoning": None,
                "position_reasoning": None,
                "volume_reasoning": None,
                "abnormal_move_reasoning": None,
            }


# 全局实例
analysis_service = AnalysisService()
