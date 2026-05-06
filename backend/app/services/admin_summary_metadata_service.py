"""
Admin Summary Metadata Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
管理员总览元数据缓存服务
使用数据库表存储预计算结果，避免每次请求都进行复杂查询
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.models import (
    AdminSummaryMetadata,
    AnalysisResult,
    Candidate,
    StockDaily,
    Task,
)
from app.schemas import AdminSummaryResponse
from app.time_utils import utc_now
from app.services.tushare_service import TushareService

logger = logging.getLogger(__name__)

# 缓存默认过期时间：1小时
DEFAULT_CACHE_TTL = timedelta(hours=1)


def get_admin_summary_metadata_service(db: Session) -> "AdminSummaryMetadataService":
    """获取元数据服务实例（依赖注入模式）"""
    return AdminSummaryMetadataService(db)


class AdminSummaryMetadataService:
    """管理员总览元数据缓存服务"""

    def __init__(self, db: Session, cache_ttl: timedelta = DEFAULT_CACHE_TTL):
        self.db = db
        self.cache_ttl = cache_ttl

    async def get_cached_summary(self) -> AdminSummaryResponse:
        """获取缓存的管理员总览数据

        如果缓存存在且未过期，直接返回
        如果缓存过期，返回旧数据并异步触发更新
        如果缓存不存在，同步计算并返回
        """
        now = utc_now()
        metadata = self._get_metadata_record()

        if metadata is None:
            # 首次访问，同步计算
            logger.info("AdminSummaryMetadata: 首次访问，同步计算缓存")
            return await self._compute_and_cache(now)

        if metadata.expires_at > now:
            # 缓存有效，直接返回
            logger.debug("AdminSummaryMetadata: 缓存命中，直接返回")
            return AdminSummaryResponse(**metadata.data)

        # 缓存过期，返回旧数据并异步触发更新
        logger.info("AdminSummaryMetadata: 缓存已过期，触发后台更新")
        asyncio.create_task(self._async_refresh_metadata(metadata.id))

        return AdminSummaryResponse(**metadata.data)

    async def force_refresh(self) -> dict:
        """强制刷新缓存

        用于用户点击刷新按钮时调用

        Returns:
            刷新结果：{"success": true, "message": "...", "from_cache": false}
        """
        now = utc_now()
        result = await self._compute_and_cache(now)
        return {
            "success": True,
            "message": "管理员总览数据已刷新",
            "from_cache": False,
            "data": result.model_dump(),
        }

    def invalidate(self) -> None:
        """清除缓存

        在任务完成时调用，确保数据及时更新
        """
        metadata = self._get_metadata_record()
        if metadata:
            # 设置过期时间为当前时间，强制下次访问时重新计算
            metadata.expires_at = utc_now()
            self.db.commit()
            logger.info("AdminSummaryMetadata: 缓存已清除")

    def _get_metadata_record(self) -> Optional[AdminSummaryMetadata]:
        """获取元数据记录"""
        return self.db.execute(
            select(AdminSummaryMetadata)
            .order_by(AdminSummaryMetadata.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    async def _compute_and_cache(self, now: datetime) -> AdminSummaryResponse:
        """计算数据并缓存到数据库

        Args:
            now: 当前时间

        Returns:
            计算得到的 AdminSummaryResponse
        """
        # 计算数据
        summary = await self._compute_summary_data()

        # 保存到数据库
        expires_at = now + self.cache_ttl
        metadata = AdminSummaryMetadata(
            data=summary.model_dump(),
            version=1,
            expires_at=expires_at,
        )
        self.db.add(metadata)
        self.db.commit()

        logger.info(f"AdminSummaryMetadata: 缓存已更新，过期时间: {expires_at}")
        return summary

    async def _async_refresh_metadata(self, old_id: int) -> None:
        """异步刷新元数据

        Args:
            old_id: 旧的元数据记录ID
        """
        try:
            now = utc_now()
            await self._compute_and_cache(now)

            # 删除旧记录
            self.db.execute(
                select(AdminSummaryMetadata)
                .where(AdminSummaryMetadata.id == old_id)
            )
            self.db.commit()

            logger.info("AdminSummaryMetadata: 后台刷新完成，旧记录已删除")
        except Exception as e:
            logger.error(f"AdminSummaryMetadata: 后台刷新失败: {e}")
            self.db.rollback()

    async def _compute_summary_data(self) -> AdminSummaryResponse:
        """计算管理员总览数据

        这是核心计算逻辑，从现有的 tasks.py 中抽取

        Returns:
            AdminSummaryResponse
        """
        from datetime import date, datetime, timedelta

        # 清理过期的活动任务
        self._cleanup_stale_active_tasks()

        tushare_service = TushareService()
        data_status = tushare_service.check_data_status()

        # 1. 获取最新交易日
        latest_trade_date = data_status.get("raw_data", {}).get("latest_trade_date")
        calendar_latest_trade_date = data_status.get("raw_data", {}).get("calendar_latest_trade_date")
        latest_db_date = data_status.get("raw_data", {}).get("latest_date")

        # 2. 获取最新候选日期
        latest_candidate_result = self.db.execute(
            select(Candidate.pick_date)
            .order_by(Candidate.pick_date.desc())
            .limit(1)
        ).first()
        latest_candidate_date = latest_candidate_result[0].isoformat() if latest_candidate_result else None

        # 3. 获取最新分析日期
        latest_analysis_result = self.db.execute(
            select(AnalysisResult.pick_date)
            .order_by(AnalysisResult.pick_date.desc())
            .limit(1)
        ).first()
        latest_analysis_date = latest_analysis_result[0].isoformat() if latest_analysis_result else None

        # 4. 计算缺口天数
        gap_days = 0
        has_gap = False
        if latest_trade_date and latest_db_date:
            try:
                trade_dt = datetime.fromisoformat(latest_trade_date).date() if isinstance(latest_trade_date, str) else latest_trade_date
                db_dt = datetime.fromisoformat(latest_db_date).date() if isinstance(latest_db_date, str) else latest_db_date
                gap = (trade_dt - db_dt).days
                if gap > 0:
                    gap_days = gap
                    has_gap = True
            except (ValueError, TypeError):
                pass

        # 5. 当前任务状态
        running_tasks = (
            self.db.query(Task)
            .filter(Task.status.in_(["pending", "running"]))
            .order_by(Task.created_at.desc())
            .all()
        )

        current_task_info = None
        task_status = "idle"
        if running_tasks:
            task = running_tasks[0]
            task_status = "running"
            meta = task.progress_meta_json or {}
            from app.schemas import AdminSummaryTaskInfo
            current_task_info = AdminSummaryTaskInfo(
                id=task.id,
                task_type=task.task_type,
                status=task.status,
                stage_label=meta.get("stage_label") or task.task_stage,
                progress=task.progress,
                summary=task.summary,
                task_stage=task.task_stage,
                progress_meta_json=meta,
            )

        # 6. 最近任务结果
        latest_completed = (
            self.db.query(Task)
            .filter(Task.status == "completed")
            .order_by(Task.completed_at.desc(), Task.id.desc())
            .first()
        )
        latest_failed = (
            self.db.query(Task)
            .filter(Task.status == "failed")
            .order_by(Task.completed_at.desc(), Task.id.desc())
            .first()
        )

        latest_task_summary = None
        if latest_completed:
            latest_task_summary = latest_completed.summary or f"任务 #{latest_completed.id} 于 {latest_completed.completed_at.strftime('%Y-%m-%d %H:%M')} 完成"
        elif latest_failed:
            latest_task_summary = latest_failed.error_message or latest_failed.summary or f"任务 #{latest_failed.id} 失败"

        # 7. 系统就绪状态
        system_ready = all([
            data_status.get("raw_data", {}).get("exists"),
            data_status.get("candidates", {}).get("exists"),
            data_status.get("analysis", {}).get("exists"),
        ])

        latest_day_stock_count = int(data_status.get("raw_data", {}).get("latest_date_stock_count") or 0)
        expected_stock_count = int(data_status.get("raw_data", {}).get("expected_stock_count") or 0)
        raw_is_latest = bool(data_status.get("raw_data", {}).get("is_latest"))
        raw_is_latest_complete = bool(data_status.get("raw_data", {}).get("is_latest_complete"))

        db_synced = bool(
            latest_db_date
            and latest_candidate_date
            and latest_analysis_date
            and latest_db_date == latest_candidate_date == latest_analysis_date
        )
        stats_ready = bool(
            db_synced
            and data_status.get("candidates", {}).get("exists")
            and data_status.get("analysis", {}).get("exists")
        )

        # 构建 pipeline_status
        from app.schemas import AdminPipelineStageSummary
        raw_csv_progress = self._assess_raw_csv_progress(latest_trade_date)

        # 获取停牌信息（从 data_status）
        suspended_count = int(data_status.get("raw_data", {}).get("suspended_count", 0))
        long_stale_count = int(data_status.get("raw_data", {}).get("long_stale_count", 0))

        pipeline_status = [
            AdminPipelineStageSummary(
                key="source_fetch",
                label="Tushare 拉取",
                status="success" if raw_is_latest_complete else ("warning" if data_status.get("raw_data", {}).get("exists") else "info"),
                ready=raw_is_latest_complete,
                value="已拉取完成" if raw_is_latest_complete else ("拉取未完成" if data_status.get("raw_data", {}).get("exists") else "待开始"),
                meta=f"最新交易日: {latest_trade_date or '-'} | 数据最新日: {latest_db_date or '-'}",
                detail=(
                    f"已就绪 {int(raw_csv_progress.get('ready_count') or 0):,} | 缺失 {int(raw_csv_progress.get('missing_count') or 0):,} | 过期 {int(raw_csv_progress.get('stale_count') or 0):,} | 异常 {int(raw_csv_progress.get('invalid_count') or 0):,}"
                    if raw_csv_progress.get("expected_total")
                    else "尚未生成原始 K 线数据"
                ),
            ),
            AdminPipelineStageSummary(
                key="db_sync",
                label="数据库同步",
                status="success" if db_synced else ("warning" if data_status.get("raw_data", {}).get("exists") else "info"),
                ready=db_synced,
                value="已同步" if db_synced else "未同步完成",
                meta=f"K线: {latest_db_date or '-'} | 候选: {latest_candidate_date or '-'} | 分析: {latest_analysis_date or '-'}",
                detail=(
                    f"候选 {int(data_status.get('candidates', {}).get('count') or 0):,} 条，分析 {int(data_status.get('analysis', {}).get('count') or 0):,} 条"
                    if data_status.get("candidates", {}).get("exists") or data_status.get("analysis", {}).get("exists")
                    else "候选与分析结果尚未生成"
                ),
            ),
            AdminPipelineStageSummary(
                key="stats_compute",
                label="结果计算",
                status="success" if stats_ready else ("warning" if data_status.get("analysis", {}).get("exists") or data_status.get("candidates", {}).get("exists") else "info"),
                ready=stats_ready,
                value="已完成" if stats_ready else "未完成",
                meta="候选清单 / 结果分析",
                detail=(
                    f"最新统计日期 {latest_analysis_date or latest_candidate_date or '-'}"
                    if data_status.get("analysis", {}).get("exists") or data_status.get("candidates", {}).get("exists")
                    else "尚未生成可用统计结果"
                ),
            ),
        ]

        # 8. 构建今日状态卡片
        raw_stock_count = data_status.get("raw_data", {}).get("stock_count", 0)
        raw_record_count = data_status.get("raw_data", {}).get("raw_record_count", 0)
        candidate_count = data_status.get("candidates", {}).get("count", 0)
        analysis_count = data_status.get("analysis", {}).get("count", 0)

        from app.schemas import AdminSummaryCard
        today_status = [
            AdminSummaryCard(
                key="raw_data",
                label="Tushare 拉取",
                value="已完成" if raw_is_latest_complete else ("进行中" if data_status.get("raw_data", {}).get("exists") else "待开始"),
                status="success" if raw_is_latest_complete else ("warning" if data_status.get("raw_data", {}).get("exists") else "info"),
                meta=f"已就绪 {int(raw_csv_progress.get('ready_count') or 0):,} / {int(raw_csv_progress.get('expected_total') or 0):,} 只 | {raw_record_count:,} 条",
            ),
            AdminSummaryCard(
                key="candidates",
                label="数据库同步",
                value="已同步" if db_synced else "未同步完成",
                status="success" if db_synced else ("warning" if data_status.get("raw_data", {}).get("exists") else "info"),
                meta=f"K线 {latest_db_date or '-'} / 候选 {latest_candidate_date or '-'} / 分析 {latest_analysis_date or '-'}",
            ),
            AdminSummaryCard(
                key="analysis",
                label="结果计算",
                value="已完成" if stats_ready else "未完成",
                status="success" if stats_ready else ("warning" if candidate_count or analysis_count else "info"),
                meta=f"候选 {candidate_count:,} 条 / 分析 {analysis_count:,} 条",
            ),
            AdminSummaryCard(
                key="task",
                label="任务状态",
                value=f"{len(running_tasks)} 运行中" if running_tasks else "空闲",
                status="warning" if running_tasks else ("danger" if latest_failed else "success"),
                meta=current_task_info.stage_label if current_task_info else (latest_task_summary or "系统正常"),
            ),
        ]

        # 9. 数据生产状态
        data_production = {
            "raw_data_exists": data_status.get("raw_data", {}).get("exists", False),
            "raw_data_count": raw_stock_count,
            "raw_data_latest": latest_db_date,
            "raw_effective_latest_trade_date": latest_trade_date,
            "raw_calendar_latest_trade_date": calendar_latest_trade_date,
            "raw_ready_count": int(raw_csv_progress.get("ready_count") or 0),
            "raw_missing_count": int(raw_csv_progress.get("missing_count") or 0),
            "raw_invalid_count": int(raw_csv_progress.get("invalid_count") or 0),
            "raw_expected_total": int(raw_csv_progress.get("expected_total") or 0),
            "raw_suspended_count": int(data_status.get("raw_data", {}).get("suspended_count", 0)),
            "raw_long_stale_count": int(data_status.get("raw_data", {}).get("long_stale_count", 0)),
            "raw_active_expected_count": int(data_status.get("raw_data", {}).get("expected_stock_count", 0)),
            "candidates_exists": data_status.get("candidates", {}).get("exists", False),
            "candidates_count": candidate_count,
            "candidates_latest": latest_candidate_date,
            "analysis_exists": data_status.get("analysis", {}).get("exists", False),
            "analysis_count": analysis_count,
            "analysis_latest": latest_analysis_date,
        }

        # 10. 数据缺口
        from app.schemas import AdminSummaryDataGap
        data_gap = AdminSummaryDataGap(
            has_gap=has_gap,
            gap_days=gap_days if has_gap else None,
            latest_local_date=latest_db_date,
            latest_trade_date=latest_trade_date,
        )

        # 11. 待处理事项
        pending_actions = []
        if has_gap and gap_days > 0:
            pending_actions.append({
                "type": "warning",
                "title": "数据缺口",
                "message": f"K线数据落后 {gap_days} 个交易日",
                "action": "增量更新",
                "route": "/update?tab=tasks&action=incremental",
            })
        if latest_failed and not (latest_completed and latest_completed.completed_at > latest_failed.completed_at):
            pending_actions.append({
                "type": "error",
                "title": "失败任务",
                "message": f"任务 #{latest_failed.id} 失败: {latest_failed.error_message or '未知错误'}",
                "action": "查看日志",
                "route": f"/update?tab=logs&taskId={latest_failed.id}",
            })
        if not system_ready:
            missing = []
            if not data_status.get("raw_data", {}).get("exists"):
                missing.append("K线数据")
            if not data_status.get("candidates", {}).get("exists"):
                missing.append("候选结果")
            if not data_status.get("analysis", {}).get("exists"):
                missing.append("分析结果")
            pending_actions.append({
                "type": "info",
                "title": "首次初始化",
                "message": f"待生成: {', '.join(missing)}",
                "action": "开始初始化",
                "route": "/update?tab=tasks&action=init",
            })

        return AdminSummaryResponse(
            today_status=today_status,
            pipeline_status=pipeline_status,
            data_production=data_production,
            data_gap=data_gap,
            current_task=current_task_info,
            latest_task={
                "id": latest_completed.id if latest_completed else None,
                "status": "completed" if latest_completed else ("failed" if latest_failed else None),
                "summary": latest_task_summary,
                "completed_at": latest_completed.completed_at.isoformat() if latest_completed and latest_completed.completed_at else None,
            },
            gap_days=gap_days,
            task_status=task_status,
            latest_task_summary=latest_task_summary,
            latest_trade_date=latest_trade_date,
            latest_db_date=latest_db_date,
            latest_candidate_date=latest_candidate_date,
            latest_analysis_date=latest_analysis_date,
            system_ready=system_ready,
            pending_actions=pending_actions,
        )

    def _cleanup_stale_active_tasks(self) -> set[int]:
        """将数据库中无对应活跃进程的 pending/running 任务标记为 cancelled"""
        from app.services.task_service import TaskService

        task_service = TaskService(self.db)
        active_tasks = (
            self.db.query(Task)
            .filter(Task.status.in_(["pending", "running"]))
            .all()
        )

        stale_ids: set[int] = set()
        for task in active_tasks:
            if task_service.is_task_process_alive(task.id):
                continue
            task.status = "cancelled"
            task.task_stage = "cancelled"
            task.progress_meta_json = TaskService._build_stage_meta(
                "cancelled", progress=task.progress, message="任务进程已结束，自动清理残留运行状态"
            )
            stale_ids.add(task.id)

        if stale_ids:
            from app.models import TaskLog
            self.db.add_all([
                TaskLog(
                    task_id=task_id,
                    level="warning",
                    stage="cancelled",
                    message="检测到残留运行状态，系统已自动清理",
                )
                for task_id in stale_ids
            ])
            self.db.commit()

        return stale_ids

    def _assess_raw_csv_progress(self, latest_trade_date: str | None) -> dict:
        """评估 CSV 文件进度（使用 tasks.py 中的实现）"""
        # 延迟导入以避免循环依赖
        from app.api.tasks import _assess_raw_csv_progress
        return _assess_raw_csv_progress(latest_trade_date)

