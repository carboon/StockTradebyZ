"""
History Backfill Service
~~~~~~~~~~~~~~~~~~~~~~~~
阶段6：一年历史回溯服务

支持初始化补齐一年历史，后续每日只补最新交易日。

核心功能：
1. 定义历史回溯数据结构
2. 实现首次历史补齐流程（初始化补齐近一年历史）
3. 实现后续按交易日增量补历史（只新增当天记录）

数据模型：
- 使用 StockAnalysis 表存储历史分析结果
- 业务键：(code, trade_date, analysis_type, strategy_version)
- 策略版本变更时自动失效旧历史记录
"""
import json
import logging
import pandas as pd
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy import select, func, and_, delete
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import StockAnalysis, Stock, StockDaily
from app.services.analysis_service import analysis_service
from app.services.tushare_service import TushareService

ROOT = Path(__file__).parent.parent.parent.parent
logger = logging.getLogger(__name__)


# 历史回溯配置
class BackfillConfig:
    """历史回溯配置"""

    # 默认回溯天数（一年约245个交易日）
    DEFAULT_BACKFILL_DAYS = 250

    # 分析类型
    ANALYSIS_TYPE = "daily_b1"

    # 策略版本（变更此值会使旧历史失效）
    STRATEGY_VERSION = "v1"

    # 最小数据要求：生成历史需要的最少交易日数据
    MIN_DATA_DAYS = 60


class HistoryBackfillStatus:
    """历史回溯状态"""

    def __init__(
        self,
        code: str,
        total_days: int = 0,
        backfilled_days: int = 0,
        latest_date: Optional[str] = None,
        strategy_version: str = BackfillConfig.STRATEGY_VERSION,
        message: str = "",
    ):
        self.code = code
        self.total_days = total_days
        self.backfilled_days = backfilled_days
        self.latest_date = latest_date
        self.strategy_version = strategy_version
        self.message = message

    @property
    def is_complete(self) -> bool:
        return self.total_days > 0 and self.backfilled_days >= self.total_days

    @property
    def progress_pct(self) -> int:
        if self.total_days == 0:
            return 0
        return int(self.backfilled_days / self.total_days * 100)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "total_days": self.total_days,
            "backfilled_days": self.backfilled_days,
            "latest_date": self.latest_date,
            "strategy_version": self.strategy_version,
            "is_complete": self.is_complete,
            "progress_pct": self.progress_pct,
            "message": self.message,
        }


class HistoryBackfillService:
    """历史回溯服务

    负责：
    1. 检查股票历史回溯状态
    2. 执行首次历史补齐
    3. 执行每日增量补齐
    """

    def __init__(self, db: Optional[Session] = None):
        self.db = db or SessionLocal()
        self.tushare_service = TushareService()
        self._owns_session = db is None

        # 缓存交易日历
        self._trade_dates_cache: Optional[List[str]] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._owns_session:
            self.db.close()

    def get_stock_backfill_status(self, code: str) -> HistoryBackfillStatus:
        """获取股票的历史回溯状态

        Args:
            code: 股票代码

        Returns:
            HistoryBackfillStatus: 回溯状态
        """
        code = code.zfill(6)

        # 获取该股票在当前策略版本下的历史记录
        result = self.db.execute(
            select(
                func.count().label("count"),
                func.max(StockAnalysis.trade_date).label("latest_date"),
            )
            .where(
                and_(
                    StockAnalysis.code == code,
                    StockAnalysis.analysis_type == BackfillConfig.ANALYSIS_TYPE,
                    StockAnalysis.strategy_version == BackfillConfig.STRATEGY_VERSION,
                )
            )
        ).first()

        backfilled_days = result.count if result else 0
        latest_date = result.latest_date.isoformat() if result and result.latest_date else None

        # 获取可用交易日数量
        available_trade_dates = self._get_available_trade_dates(code)
        total_days = len(available_trade_dates)

        message = ""
        if backfilled_days == 0:
            message = "尚未执行历史补齐"
        elif backfilled_days < total_days:
            message = f"已补齐 {backfilled_days}/{total_days} 天"
        else:
            message = "历史补齐完成"

        return HistoryBackfillStatus(
            code=code,
            total_days=total_days,
            backfilled_days=backfilled_days,
            latest_date=latest_date,
            strategy_version=BackfillConfig.STRATEGY_VERSION,
            message=message,
        )

    def _get_available_trade_dates(self, code: str) -> List[str]:
        """获取股票可用的交易日列表

        Args:
            code: 股票代码

        Returns:
            可用交易日列表（YYYY-MM-DD格式）
        """
        # 从 stock_daily 表获取该股票的所有交易日
        result = self.db.execute(
            select(StockDaily.trade_date)
            .where(StockDaily.code == code)
            .order_by(StockDaily.trade_date.desc())
            .limit(BackfillConfig.DEFAULT_BACKFILL_DAYS)
        ).all()

        return [row[0].isoformat() for row in result]

    def get_missing_trade_dates(
        self,
        code: str,
        target_date: Optional[str] = None,
    ) -> List[str]:
        """获取需要补齐的交易日列表

        Args:
            code: 股票代码
            target_date: 目标日期（YYYY-MM-DD），默认补齐到最新可用交易日

        Returns:
            需要补齐的交易日列表
        """
        code = code.zfill(6)

        # 获取已补齐的日期
        existing_dates_result = self.db.execute(
            select(StockAnalysis.trade_date)
            .where(
                and_(
                    StockAnalysis.code == code,
                    StockAnalysis.analysis_type == BackfillConfig.ANALYSIS_TYPE,
                    StockAnalysis.strategy_version == BackfillConfig.STRATEGY_VERSION,
                )
            )
            .order_by(StockAnalysis.trade_date.desc())
        ).all()

        existing_dates = {row[0].isoformat() for row in existing_dates_result}

        # 获取可用的交易日
        available_dates = self._get_available_trade_dates(code)

        # 如果指定了目标日期，只补齐到该日期
        if target_date:
            available_dates = [d for d in available_dates if d <= target_date]

        # 返回缺失的日期（按时间正序）
        missing_dates = [d for d in reversed(available_dates) if d not in existing_dates]

        return missing_dates

    def backfill_stock_history(
        self,
        code: str,
        target_date: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> HistoryBackfillStatus:
        """补齐股票历史分析数据

        Args:
            code: 股票代码
            target_date: 目标日期（YYYY-MM-DD），默认补齐到最新可用交易日
            progress_callback: 进度回调函数

        Returns:
            HistoryBackfillStatus: 补齐后的状态
        """
        code = code.zfill(6)

        # 获取需要补齐的日期
        missing_dates = self.get_missing_trade_dates(code, target_date)

        if not missing_dates:
            status = self.get_stock_backfill_status(code)
            status.message = "历史数据已是最新"
            return status

        total = len(missing_dates)
        completed = 0
        failed = 0

        # 获取股票数据
        df = analysis_service.load_stock_data(code, days=BackfillConfig.DEFAULT_BACKFILL_DAYS + 60)
        if df is None or df.empty:
            return HistoryBackfillStatus(
                code=code,
                total_days=0,
                backfilled_days=0,
                message=f"股票 {code} 数据不存在",
            )

        # 构建分析器
        selector = analysis_service._build_b1_selector()
        quant_config = analysis_service._load_quant_review_config()

        # 逐个交易日生成分析结果
        for trade_date_str in missing_dates:
            try:
                # 获取该日期之前的数据
                trade_date = datetime.strptime(trade_date_str, "%Y-%m-%d")
                df_before = df[df["date"] <= trade_date].copy()

                if len(df_before) < BackfillConfig.MIN_DATA_DAYS:
                    logger.warning(f"{code} {trade_date_str} 数据不足，跳过")
                    failed += 1
                    continue

                # 准备数据
                df_prepared = selector.prepare_df(df_before)
                if df_prepared.empty:
                    logger.warning(f"{code} {trade_date_str} 无有效数据，跳过")
                    failed += 1
                    continue

                # 查找最接近的日期
                valid_dates = df_prepared.index[df_prepared.index <= trade_date]
                if valid_dates.empty:
                    logger.warning(f"{code} {trade_date_str} 无有效数据，跳过")
                    failed += 1
                    continue
                check_row = df_prepared.loc[valid_dates[-1]]

                # 提取指标
                b1_passed = bool(check_row.get("_vec_pick", False))
                kdj_j = float(check_row["J"]) if pd.notna(check_row.get("J")) else None
                zx_long_pos = bool(check_row["zxdq"] > check_row["zxdkx"]) if pd.notna(check_row.get("zxdq")) and pd.notna(check_row.get("zxdkx")) else None
                weekly_ma_aligned = bool(check_row["wma_bull"]) if pd.notna(check_row.get("wma_bull")) else None
                volume_healthy = analysis_service._calculate_volume_health(df_prepared)

                # 执行量化评分
                score_result = analysis_service._quant_review_for_date(
                    code, df_before, trade_date_str, config=quant_config
                )

                # 获取收盘价
                close_price = float(check_row["close"]) if pd.notna(check_row.get("close")) else None

                # 检查是否已存在（避免并发重复插入）
                existing = self.db.query(StockAnalysis).filter(
                    and_(
                        StockAnalysis.code == code,
                        StockAnalysis.trade_date == date.fromisoformat(trade_date_str),
                        StockAnalysis.analysis_type == BackfillConfig.ANALYSIS_TYPE,
                        StockAnalysis.strategy_version == BackfillConfig.STRATEGY_VERSION,
                    )
                ).first()

                if not existing:
                    # 创建新记录
                    record = StockAnalysis(
                        code=code,
                        trade_date=date.fromisoformat(trade_date_str),
                        analysis_type=BackfillConfig.ANALYSIS_TYPE,
                        strategy_version=BackfillConfig.STRATEGY_VERSION,
                        close_price=close_price,
                        verdict=score_result.get("verdict"),
                        score=score_result.get("score"),
                        signal_type=score_result.get("signal_type"),
                        b1_passed=b1_passed,
                        kdj_j=kdj_j,
                        zx_long_pos=zx_long_pos,
                        weekly_ma_aligned=weekly_ma_aligned,
                        volume_healthy=volume_healthy,
                        details_json={
                            "kdj_j": kdj_j,
                            "zx_long_pos": zx_long_pos,
                            "weekly_ma_aligned": weekly_ma_aligned,
                            "volume_healthy": volume_healthy,
                            "score": score_result.get("score"),
                            "verdict": score_result.get("verdict"),
                            "signal_type": score_result.get("signal_type"),
                        },
                    )
                    self.db.add(record)

                completed += 1

                # 每处理10条记录提交一次
                if completed % 10 == 0:
                    self.db.commit()

                # 进度回调
                if progress_callback:
                    progress_callback({
                        "code": code,
                        "total": total,
                        "completed": completed,
                        "failed": failed,
                        "current_date": trade_date_str,
                        "progress_pct": int((completed + failed) / total * 100),
                    })

            except Exception as e:
                logger.error(f"补齐 {code} {trade_date_str} 失败: {e}")
                failed += 1
                continue

        # 最终提交
        self.db.commit()

        # 返回最终状态
        final_status = self.get_stock_backfill_status(code)
        if failed > 0:
            final_status.message = f"补齐完成：{completed} 成功, {failed} 失败"
        else:
            final_status.message = f"成功补齐 {completed} 天历史数据"

        return final_status

    def backfill_multiple_stocks(
        self,
        codes: List[str],
        target_date: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """批量补齐多只股票的历史数据

        Args:
            codes: 股票代码列表
            target_date: 目标日期
            progress_callback: 进度回调

        Returns:
            总体补齐状态
        """
        total = len(codes)
        completed = 0
        failed = 0
        results = []

        for code in codes:
            try:
                status = self.backfill_stock_history(code, target_date)
                results.append(status.to_dict())
                completed += 1
            except Exception as e:
                logger.error(f"补齐 {code} 失败: {e}")
                failed += 1
                results.append({
                    "code": code,
                    "error": str(e),
                })

            if progress_callback:
                progress_callback({
                    "total": total,
                    "completed": completed + failed,
                    "current_code": code,
                    "progress_pct": int((completed + failed) / total * 100),
                })

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "results": results,
        }

    def incremental_backfill_latest_trade_date(self, code: str) -> HistoryBackfillStatus:
        """增量补齐最新交易日

        只补齐当前最新交易日的历史记录，不重复回算已有历史。

        Args:
            code: 股票代码

        Returns:
            补齐后的状态
        """
        code = code.zfill(6)

        # 获取最新可用交易日
        available_dates = self._get_available_trade_dates(code)
        if not available_dates:
            return HistoryBackfillStatus(
                code=code,
                message="无可用交易日数据",
            )

        latest_trade_date = available_dates[0]  # 已按日期降序排序

        # 检查最新交易日是否已补齐
        existing = self.db.query(StockAnalysis).filter(
            and_(
                StockAnalysis.code == code,
                StockAnalysis.trade_date == date.fromisoformat(latest_trade_date),
                StockAnalysis.analysis_type == BackfillConfig.ANALYSIS_TYPE,
                StockAnalysis.strategy_version == BackfillConfig.STRATEGY_VERSION,
            )
        ).first()

        if existing:
            status = self.get_stock_backfill_status(code)
            status.message = "最新交易日已补齐"
            return status

        # 只补齐最新交易日
        return self.backfill_stock_history(code, target_date=latest_trade_date)

    def get_batch_backfill_status(self, codes: List[str]) -> Dict[str, Any]:
        """获取批量股票的历史回溯状态

        Args:
            codes: 股票代码列表

        Returns:
            批量状态汇总
        """
        total = len(codes)
        complete = 0
        partial = 0
        not_started = 0
        details = []

        for code in codes:
            status = self.get_stock_backfill_status(code)
            details.append(status.to_dict())

            if status.is_complete:
                complete += 1
            elif status.backfilled_days > 0:
                partial += 1
            else:
                not_started += 1

        return {
            "total": total,
            "complete": complete,
            "partial": partial,
            "not_started": not_started,
            "details": details,
        }

    def invalidate_strategy_version(self, old_version: str) -> int:
        """使旧策略版本的历史记录失效

        当策略版本变更时，可以删除旧版本的历史记录。

        Args:
            old_version: 旧策略版本

        Returns:
            删除的记录数
        """
        # 先统计数量
        count = self.db.query(StockAnalysis).filter(
            StockAnalysis.strategy_version == old_version
        ).count()

        if count > 0:
            # 执行删除
            self.db.query(StockAnalysis).filter(
                StockAnalysis.strategy_version == old_version
            ).delete(synchronize_session=False)
            self.db.commit()
            logger.info(f"已删除策略版本 {old_version} 的 {count} 条历史记录")

        return count

    def initialize_year_history(
        self,
        code: str,
        progress_callback: Optional[callable] = None,
    ) -> HistoryBackfillStatus:
        """初始化补齐近一年历史

        这是首次历史补齐的入口，会补齐近约250个交易日的历史数据。

        Args:
            code: 股票代码
            progress_callback: 进度回调

        Returns:
            补齐后的状态
        """
        code = code.zfill(6)

        # 检查是否已经初始化过
        status = self.get_stock_backfill_status(code)
        if status.backfilled_days >= BackfillConfig.DEFAULT_BACKFILL_DAYS:
            status.message = "历史数据已完整，无需重新初始化"
            return status

        # 如果已有部分数据，先清理旧版本数据（确保数据一致性）
        if status.backfilled_days > 0:
            logger.info(f"清理 {code} 的旧历史数据，准备重新初始化")
            self.db.query(StockAnalysis).filter(
                and_(
                    StockAnalysis.code == code,
                    StockAnalysis.analysis_type == BackfillConfig.ANALYSIS_TYPE,
                    StockAnalysis.strategy_version == BackfillConfig.STRATEGY_VERSION,
                )
            ).delete(synchronize_session=False)
            self.db.commit()

        # 执行完整补齐
        return self.backfill_stock_history(code, progress_callback=progress_callback)


# 全局实例
_history_backfill_service: Optional[HistoryBackfillService] = None


def get_history_backfill_service() -> HistoryBackfillService:
    """获取历史回溯服务单例"""
    global _history_backfill_service
    if _history_backfill_service is None:
        _history_backfill_service = HistoryBackfillService()
    return _history_backfill_service
