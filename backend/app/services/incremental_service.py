"""
Incremental Data Fill Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
阶段3：区间增量更新服务

支持停服、迁移、维护后的一段时间内数据缺口补齐。
核心功能：
1. 识别数据缺口区间
2. 按交易日逐步补齐行情数据
3. 对增量新增交易日逐日生成明日之星结果
4. 对区间内每个交易日的 Top5 生成单股诊断结果

状态模型：
- gap_status: 数据缺口状态
- kline_fill_status: 行情补齐状态
- tomorrow_star_status: 明日之星补齐状态
- top5_diagnosis_status: Top5诊断补齐状态
- history_fill_status: 历史补齐状态
"""
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import StockDaily, Candidate, AnalysisResult, DailyB1Check, Task
from app.services.tushare_service import TushareService
from app.services.analysis_service import analysis_service

ROOT = Path(__file__).parent.parent.parent.parent
logger = logging.getLogger(__name__)


class GapInfo:
    """数据缺口信息"""

    def __init__(
        self,
        latest_local_date: Optional[str],
        latest_trade_date: Optional[str],
        missing_dates: List[str],
    ):
        self.latest_local_date = latest_local_date
        self.latest_trade_date = latest_trade_date
        self.missing_dates = missing_dates

    @property
    def has_gap(self) -> bool:
        return len(self.missing_dates) > 0

    @property
    def gap_days(self) -> int:
        return len(self.missing_dates)

    @property
    def gap_start(self) -> Optional[str]:
        return self.missing_dates[0] if self.missing_dates else None

    @property
    def gap_end(self) -> Optional[str]:
        return self.missing_dates[-1] if self.missing_dates else None


class FillStatus:
    """补齐状态"""

    def __init__(
        self,
        stage: str,
        status: str,  # pending, in_progress, completed, failed
        total: int = 0,
        completed: int = 0,
        failed: int = 0,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.stage = stage
        self.status = status
        self.total = total
        self.completed = completed
        self.failed = failed
        self.message = message
        self.details = details or {}

    @property
    def progress_pct(self) -> int:
        if self.total == 0:
            return 0
        return int(self.completed / self.total * 100)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "failed": self.failed,
            "progress_pct": self.progress_pct,
            "message": self.message,
            "details": self.details,
        }


class IncrementalFillService:
    """区间增量更新服务

    负责识别数据缺口并按步骤补齐：
    1. 识别缺口（任务 3.1）
    2. 补齐行情数据（任务 3.2）
    3. 补齐明日之星结果（任务 3.3）
    4. 补齐 Top5 诊断与历史（任务 3.4）
    """

    # 服务状态
    STAGES = [
        "gap_detection",      # 3.1: 识别缺口
        "kline_fill",         # 3.2: 补齐行情
        "tomorrow_star",      # 3.3: 补齐明日之星
        "top5_diagnosis",     # 3.4: 补齐 Top5 诊断
        "history_fill",       # 3.4: 补齐历史
    ]

    def __init__(self, db: Optional[Session] = None):
        self.db = db or SessionLocal()
        self.tushare_service = TushareService()
        self._owns_session = db is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._owns_session:
            self.db.close()

    def get_gap_info(self) -> GapInfo:
        """任务 3.1：识别数据缺口

        Returns:
            GapInfo: 缺口信息
        """
        # 获取本地最新交易日
        with SessionLocal() as db:
            result = db.execute(
                select(StockDaily.trade_date)
                .order_by(StockDaily.trade_date.desc())
                .limit(1)
            ).first()
            latest_local_date = result[0].isoformat() if result else None

        # 获取最新交易日
        latest_trade_date = self.tushare_service.get_latest_trade_date()

        # 计算缺失的交易日
        missing_dates = []
        if latest_trade_date and latest_local_date:
            missing_dates = self._get_missing_trade_dates(
                latest_local_date,
                latest_trade_date
            )

        return GapInfo(
            latest_local_date=latest_local_date,
            latest_trade_date=latest_trade_date,
            missing_dates=missing_dates,
        )

    def _get_missing_trade_dates(
        self,
        start_date: str,
        end_date: str,
    ) -> List[str]:
        """获取两个日期之间缺失的交易日列表

        Args:
            start_date: 开始日期 (YYYY-MM-DD)，不包含
            end_date: 结束日期 (YYYY-MM-DD)，包含

        Returns:
            缺失的交易日列表
        """
        try:
            import tushare as ts
            token = self.tushare_service.token
            pro = ts.pro_api(token)

            # 规范化日期格式
            start = start_date.replace("-", "")
            end = end_date.replace("-", "")

            # 获取交易日历
            df = pro.trade_cal(exchange="SSE", start_date=start, end_date=end)
            if df is None or df.empty:
                return []

            # 筛选出交易日且在区间内的日期
            trade_dates = []
            for _, row in df.iterrows():
                cal_date = row["cal_date"]
                is_open = row["is_open"]

                # 转换为 YYYY-MM-DD 格式比较
                date_str = f"{cal_date[:4]}-{cal_date[4:6]}-{cal_date[6:]}"

                # 只选择在区间内且是交易日的日期
                if is_open == 1 and date_str > start_date and date_str <= end_date:
                    trade_dates.append(date_str)

            return trade_dates
        except Exception as e:
            logger.error(f"获取交易日历失败: {e}")
            return []

    def detect_gap_status(self) -> Dict[str, Any]:
        """任务 3.1：检测缺口状态

        Returns:
            包含以下字段的字典：
            - has_gap: 是否存在缺口
            - latest_local_date: 本地最新日期
            - latest_trade_date: 最新交易日
            - gap_days: 缺口天数
            - gap_start: 缺口开始日期
            - gap_end: 缺口结束日期
            - missing_dates: 缺失日期列表
        """
        gap_info = self.get_gap_info()

        return {
            "has_gap": gap_info.has_gap,
            "latest_local_date": gap_info.latest_local_date,
            "latest_trade_date": gap_info.latest_trade_date,
            "gap_days": gap_info.gap_days,
            "gap_start": gap_info.gap_start,
            "gap_end": gap_info.gap_end,
            "missing_dates": gap_info.missing_dates,
        }

    def fill_kline_data(
        self,
        target_date: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> FillStatus:
        """任务 3.2：补齐行情数据

        按缺失交易日逐步补齐行情数据，不要求重新全量初始化。

        Args:
            target_date: 目标日期 (YYYY-MM-DD)，默认补齐到最新交易日
            progress_callback: 进度回调函数

        Returns:
            FillStatus: 补齐状态
        """
        gap_info = self.get_gap_info()

        if not gap_info.has_gap:
            return FillStatus(
                stage="kline_fill",
                status="completed",
                total=0,
                completed=0,
                message="数据已是最新，无需补齐",
            )

        # 确定补齐的目标日期
        end_date = target_date or gap_info.latest_trade_date
        if not end_date:
            return FillStatus(
                stage="kline_fill",
                status="failed",
                total=0,
                completed=0,
                message="无法确定目标日期",
            )

        # 获取需要补齐的日期
        latest_local = gap_info.latest_local_date or "2024-01-01"
        missing_dates = self._get_missing_trade_dates(latest_local, end_date)

        if not missing_dates:
            return FillStatus(
                stage="kline_fill",
                status="completed",
                total=0,
                completed=0,
                message="没有需要补齐的交易日",
            )

        total = len(missing_dates)
        completed = 0
        failed = 0

        status = FillStatus(
            stage="kline_fill",
            status="in_progress",
            total=total,
            completed=0,
            message=f"准备补齐 {total} 个交易日的行情数据",
        )

        if progress_callback:
            progress_callback(status.to_dict())

        # 获取股票列表
        with SessionLocal() as db:
            from app.models import Stock
            codes = [row[0] for row in db.execute(select(Stock.code)).all()]

        if not codes:
            return FillStatus(
                stage="kline_fill",
                status="failed",
                total=total,
                completed=0,
                message="没有找到股票列表",
            )

        # 补齐行情数据
        from app.services.daily_data_service import DailyDataService
        daily_service = DailyDataService()

        for i, trade_date in enumerate(missing_dates):
            try:
                # 检查该日期的数据是否已在 Tushare 可读
                if not self.tushare_service.is_trade_date_data_ready(trade_date):
                    logger.warning(f"日期 {trade_date} 的数据尚未在 Tushare 可读，跳过")
                    failed += 1
                    continue

                # 对该日期的股票进行增量更新
                # 注意：这里需要为每个日期单独处理
                # 使用 daily_service 的增量更新逻辑，但限制到特定日期
                raw_dir = ROOT / settings.raw_data_dir
                raw_dir.mkdir(parents=True, exist_ok=True)

                for code in codes:
                    try:
                        df = daily_service.fetch_daily_data(
                            code,
                            start_date=trade_date.replace("-", ""),
                            end_date=trade_date.replace("-", ""),
                        )
                        if df is not None and not df.empty:
                            daily_service.save_daily_data(df)
                            self._sync_csv_for_code(code, df, raw_dir)
                    except Exception as e:
                        logger.debug(f"补齐 {code} {trade_date} 数据失败: {e}")
                        continue

                completed += 1

                # 更新进度
                if progress_callback:
                    status = FillStatus(
                        stage="kline_fill",
                        status="in_progress",
                        total=total,
                        completed=completed,
                        failed=failed,
                        message=f"已补齐 {completed}/{total} 个交易日",
                        details={"current_date": trade_date},
                    )
                    progress_callback(status.to_dict())

            except Exception as e:
                logger.error(f"补齐日期 {trade_date} 失败: {e}")
                failed += 1
                continue

        final_status = "completed" if completed == total else ("failed" if completed == 0 else "partial")
        return FillStatus(
            stage="kline_fill",
            status=final_status,
            total=total,
            completed=completed,
            failed=failed,
            message=f"行情补齐完成: {completed} 成功, {failed} 失败",
            details={
                "gap_start": missing_dates[0] if missing_dates else None,
                "gap_end": missing_dates[-1] if missing_dates else None,
            },
        )

    @staticmethod
    def _sync_csv_for_code(code: str, new_df: pd.DataFrame, raw_dir: Path) -> None:
        """将新增日线数据同步到 CSV 文件。

        读取已有 CSV（如果存在），合并新数据（按 date 去重），写回。
        CSV 列格式：date, open, close, high, low, volume
        """
        csv_path = raw_dir / f"{code}.csv"

        # 转换 DataFrame 列为 CSV 格式
        csv_df = new_df.rename(columns={"trade_date": "date"})
        csv_df = csv_df[["date", "open", "close", "high", "low", "volume"]].copy()
        csv_df["date"] = pd.to_datetime(csv_df["date"])

        if csv_path.exists():
            try:
                existing = pd.read_csv(csv_path)
                if not existing.empty:
                    existing["date"] = pd.to_datetime(existing["date"])
                    csv_df = pd.concat([existing, csv_df], ignore_index=True)
            except Exception:
                pass

        csv_df = csv_df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
        csv_df.to_csv(csv_path, index=False)

    def fill_tomorrow_star_results(
        self,
        target_date: Optional[str] = None,
        reviewer: str = "quant",
        progress_callback: Optional[callable] = None,
    ) -> FillStatus:
        """任务 3.3：补齐明日之星结果

        对增量新增交易日逐日生成：
        - 候选结果
        - 评分结果
        - Top5 推荐

        Args:
            target_date: 目标日期 (YYYY-MM-DD)
            reviewer: 评审者类型
            progress_callback: 进度回调

        Returns:
            FillStatus: 补齐状态
        """
        # 获取已有明日之星结果的日期
        existing_dates = self._get_existing_tomorrow_star_dates()

        # 获取需要补齐的日期
        if target_date:
            # 获取从最新已有日期到目标日期之间的交易日
            latest_existing = max(existing_dates) if existing_dates else "2024-01-01"
            missing_dates = self._get_missing_trade_dates(latest_existing, target_date)
        else:
            # 获取所有缺失的交易日
            gap_info = self.get_gap_info()
            missing_dates = gap_info.missing_dates

        # 过滤出还没有候选结果的日期
        missing_dates = [d for d in missing_dates if d not in existing_dates]

        if not missing_dates:
            return FillStatus(
                stage="tomorrow_star",
                status="completed",
                total=0,
                completed=0,
                message="明日之星结果已是最新",
            )

        total = len(missing_dates)
        completed = 0
        failed = 0

        if progress_callback:
            progress_callback(FillStatus(
                stage="tomorrow_star",
                status="in_progress",
                total=total,
                completed=0,
                message=f"准备生成 {total} 个交易日的明日之星结果",
            ).to_dict())

        # 为每个缺失日期生成结果
        for trade_date in missing_dates:
            try:
                # 检查该日期的行情数据是否已存在
                if not self._check_kline_data_exists(trade_date):
                    logger.warning(f"日期 {trade_date} 的行情数据不存在，跳过生成明日之星")
                    failed += 1
                    continue

                # 运行明日之星生成流程
                result = self._run_tomorrow_star_for_date(trade_date, reviewer)

                if result.get("success"):
                    completed += 1
                else:
                    failed += 1

                if progress_callback:
                    progress_callback(FillStatus(
                        stage="tomorrow_star",
                        status="in_progress",
                        total=total,
                        completed=completed,
                        failed=failed,
                        message=f"已生成 {completed}/{total} 个日期的结果",
                        details={"current_date": trade_date},
                    ).to_dict())

            except Exception as e:
                logger.error(f"生成日期 {trade_date} 的明日之星结果失败: {e}")
                failed += 1
                continue

        final_status = "completed" if completed == total else ("failed" if completed == 0 else "partial")
        return FillStatus(
            stage="tomorrow_star",
            status=final_status,
            total=total,
            completed=completed,
            failed=failed,
            message=f"明日之星补齐完成: {completed} 成功, {failed} 失败",
        )

    def _get_existing_tomorrow_star_dates(self) -> List[str]:
        """获取已有明日之星结果的日期列表"""
        candidates_dir = ROOT / settings.candidates_dir
        dates = []

        for file in candidates_dir.glob("candidates_*.json"):
            if file.name == "candidates_latest.json":
                continue
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    pick_date = data.get("pick_date")
                    if pick_date:
                        dates.append(pick_date)
            except Exception:
                continue

        return sorted(dates)

    def _check_kline_data_exists(self, trade_date: str) -> bool:
        """检查指定日期的行情数据是否存在"""
        try:
            target = date.fromisoformat(trade_date)
            with SessionLocal() as db:
                count = db.execute(
                    select(func.count())
                    .select_from(StockDaily)
                    .where(StockDaily.trade_date == target)
                ).scalar()
                return count > 0
        except Exception:
            return False

    def _run_tomorrow_star_for_date(self, trade_date: str, reviewer: str) -> Dict[str, Any]:
        """为指定日期运行明日之星生成流程

        这是一个简化版本，直接调用相关服务而不是完整 run_all.py
        """
        import subprocess
        import sys

        # 构建命令
        cmd = [
            sys.executable,
            str(ROOT / "run_all.py"),
            "--reviewer", reviewer,
            "--db",
        ]

        # 设置环境变量指定日期
        env = {
            "TARGET_DATE": trade_date,
            "PYTHONPATH": str(ROOT),
        }

        try:
            # 运行命令
            result = subprocess.run(
                cmd,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=3600,  # 1小时超时
                env={**subprocess.os.environ, **env},
            )

            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "timeout",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def fill_top5_diagnosis_and_history(
        self,
        target_date: Optional[str] = None,
        reviewer: str = "quant",
        progress_callback: Optional[callable] = None,
    ) -> FillStatus:
        """任务 3.4：补齐 Top5 诊断与历史

        对区间内每个交易日的 Top5 股票生成单股诊断结果，
        并补齐每日检查历史。

        Args:
            target_date: 目标日期
            reviewer: 评审者
            progress_callback: 进度回调

        Returns:
            FillStatus: 补齐状态
        """
        # 获取需要补齐的日期
        if target_date:
            gap_info = self.get_gap_info()
            latest_existing = gap_info.latest_local_date or "2024-01-01"
            missing_dates = self._get_missing_trade_dates(latest_existing, target_date)
        else:
            gap_info = self.get_gap_info()
            missing_dates = gap_info.missing_dates

        # 只处理已有候选结果的日期
        existing_dates = self._get_existing_tomorrow_star_dates()
        target_dates = [d for d in missing_dates if d in existing_dates]

        if not target_dates:
            return FillStatus(
                stage="top5_diagnosis",
                status="completed",
                total=0,
                completed=0,
                message="Top5 诊断已是最新",
            )

        total = len(target_dates)
        completed = 0
        failed = 0

        if progress_callback:
            progress_callback(FillStatus(
                stage="top5_diagnosis",
                status="in_progress",
                total=total,
                completed=0,
                message=f"准备生成 {total} 个日期的 Top5 诊断",
            ).to_dict())

        # 为每个日期处理 Top5
        for trade_date in target_dates:
            try:
                # 获取该日期的 Top5 股票
                top5_codes = self._get_top5_codes_for_date(trade_date)

                if not top5_codes:
                    logger.info("日期 %s 没有可补齐的 Top5 股票，跳过", trade_date)
                    completed += 1
                    continue

                # 为每只 Top5 股票生成历史检查数据
                for code in top5_codes:
                    try:
                        self._ensure_stock_history(code, trade_date)
                    except Exception as e:
                        logger.error(f"生成 {code} 历史数据失败: {e}")
                        continue

                completed += 1

                if progress_callback:
                    progress_callback(FillStatus(
                        stage="top5_diagnosis",
                        status="in_progress",
                        total=total,
                        completed=completed,
                        failed=failed,
                        message=f"已处理 {completed}/{total} 个日期",
                        details={"current_date": trade_date, "top5_count": len(top5_codes)},
                    ).to_dict())

            except Exception as e:
                logger.error(f"处理日期 {trade_date} 的 Top5 诊断失败: {e}")
                failed += 1
                continue

        final_status = "completed" if completed == total else ("failed" if completed == 0 else "partial")
        return FillStatus(
            stage="top5_diagnosis",
            status=final_status,
            total=total,
            completed=completed,
            failed=failed,
            message=f"Top5 诊断补齐完成: {completed} 成功, {failed} 失败",
        )

    def _get_top5_codes_for_date(self, trade_date: str) -> List[str]:
        """获取指定日期的 Top5 股票代码"""
        suggestion_file = ROOT / settings.review_dir / trade_date / "suggestion.json"

        if suggestion_file.exists():
            try:
                with open(suggestion_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                recommendations = data.get("recommendations", [])
                codes = [str(r.get("code", "")).zfill(6) for r in recommendations[:5] if r.get("code")]
                if codes:
                    return codes
            except Exception:
                logger.warning("读取 suggestion.json 失败，回退到数据库: %s", suggestion_file)

        try:
            pick_date = date.fromisoformat(trade_date)
        except ValueError:
            return []

        threshold = float(settings.min_score_threshold)
        rows = (
            self.db.query(AnalysisResult.code)
            .filter(
                AnalysisResult.pick_date == pick_date,
                AnalysisResult.verdict == "PASS",
                AnalysisResult.total_score.isnot(None),
                AnalysisResult.total_score >= threshold,
            )
            .order_by(
                AnalysisResult.total_score.desc(),
                AnalysisResult.id.asc(),
            )
            .limit(5)
            .all()
        )
        return [str(code).zfill(6) for code, in rows if str(code or "").strip()]

    def _ensure_stock_history(self, code: str, asof_date: str) -> None:
        """确保股票的历史检查数据存在

        如果不存在，则调用 analysis_service 生成历史数据
        """
        history_dir = ROOT / settings.review_dir / "history"
        stock_history_file = history_dir / f"{code}.json"

        # 检查历史文件是否存在
        if stock_history_file.exists():
            try:
                with open(stock_history_file, "r") as f:
                    data = json.load(f)
                history = data.get("history", [])

                # 检查是否包含目标日期
                for item in history:
                    if item.get("check_date") == asof_date:
                        return  # 已存在，无需生成
            except Exception:
                pass

        # 生成历史数据（30天）
        result = analysis_service.generate_stock_history_checks(
            code,
            days=30,
            clean=False,  # 不清理已有数据
        )

        if not result.get("success"):
            raise Exception(f"生成历史数据失败: {result.get('error')}")

    def get_fill_summary(self) -> Dict[str, Any]:
        """获取区间增量更新总览

        Returns:
            包含各阶段状态的字典
        """
        gap_status = self.detect_gap_status()

        # 检查明日之星状态
        existing_star_dates = self._get_existing_tomorrow_star_dates()
        latest_star_date = max(existing_star_dates) if existing_star_dates else None

        # 检查历史数据状态
        history_dir = ROOT / settings.review_dir / "history"
        history_count = len(list(history_dir.glob("*.json"))) if history_dir.exists() else 0

        return {
            "gap": gap_status,
            "tomorrow_star": {
                "latest_date": latest_star_date,
                "total_dates": len(existing_star_dates),
            },
            "history": {
                "stock_count": history_count,
            },
            "can_fill": gap_status.get("has_gap", False),
            "recommended_action": self._get_recommended_action(gap_status, latest_star_date),
        }

    def _get_recommended_action(self, gap_status: Dict, latest_star_date: Optional[str]) -> str:
        """获取推荐操作"""
        if not gap_status.get("has_gap"):
            return "数据已是最新"

        gap_days = gap_status.get("gap_days", 0)

        if gap_days == 0:
            return "无需补齐"

        if gap_days <= 5:
            return f"建议执行增量更新（{gap_days} 天）"
        elif gap_days <= 30:
            return f"建议执行区间增量更新（{gap_days} 天）"
        else:
            return f"缺口较大（{gap_days} 天），建议检查数据源后执行全量初始化"


# 全局实例
_incremental_fill_service: Optional[IncrementalFillService] = None


def get_incremental_fill_service() -> IncrementalFillService:
    """获取区间增量更新服务单例"""
    global _incremental_fill_service
    if _incremental_fill_service is None:
        _incremental_fill_service = IncrementalFillService()
    return _incremental_fill_service
