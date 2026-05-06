"""
Task Service
~~~~~~~~~~~~
后台任务服务，集成 run_all.py

## 日志策略（阶段3优化）
任务日志持久化策略：
1. 结构化进度行（is_progress_line=True）只更新状态，不写日志表
2. 使用缓冲区批量写入日志，每30秒或50条批量写入一次
3. 任务关键状态变更（pending->running, completed等）立即写库
4. 普通日志行批量聚合写入

## 预期效果
- 长时间运行任务的日志写入频率降低约80%
- 减少对任务执行性能的影响
"""
import asyncio
import json
import locale
import logging
import math
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from app.time_utils import utc_now

ROOT = Path(__file__).parent.parent.parent.parent

logger = logging.getLogger(__name__)


def _should_skip_task_log_line(message: str) -> bool:
    """过滤无价值高噪音日志，避免挤占任务日志与刷新带宽。"""
    text = (message or "").strip()
    if not text:
        return True

    lower = text.lower()
    if "sqlalchemy.engine.engine" in lower:
        return True
    if text.startswith("SELECT ") or text.startswith("INSERT ") or text.startswith("UPDATE ") or text.startswith("DELETE "):
        return True
    if text.startswith("FROM ") or text.startswith("WHERE "):
        return True
    if text.startswith("[cached since ") or text.startswith("[generated in "):
        return True
    return False


# 任务日志缓冲区
class TaskLogBuffer:
    """任务日志缓冲区，支持批量写入。"""

    def __init__(self, flush_interval: int = 30, flush_threshold: int = 50):
        self._buffer: dict[int, List[dict]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._flush_interval = flush_interval
        self._flush_threshold = flush_threshold
        self._running = False

    def add(
        self,
        task_id: int,
        level: str,
        message: str,
        stage: Optional[str] = None,
        immediate: bool = False,
    ) -> None:
        """添加日志到缓冲区。

        Args:
            task_id: 任务ID
            level: 日志级别
            message: 日志消息
            stage: 任务阶段
            immediate: 是否立即写入（用于关键状态变更）
        """
        if immediate:
            self._flush_single(task_id, level, message, stage)
            return

        with self._lock:
            self._buffer[task_id].append({
                "level": level,
                "message": message,
                "stage": stage,
            })
            if len(self._buffer[task_id]) >= self._flush_threshold:
                self._flush_task(task_id)

    def _flush_single(self, task_id: int, level: str, message: str, stage: Optional[str] = None) -> None:
        """立即写入单条日志（用于关键状态变更）。"""
        from app.database import SessionLocal
        from app.models import TaskLog

        db = SessionLocal()
        should_close = "PYTEST_CURRENT_TEST" not in os.environ
        try:
            log = TaskLog(
                task_id=task_id,
                level=level,
                stage=stage,
                message=message,
            )
            db.add(log)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("写入任务日志失败: %s", e)
        finally:
            if should_close:
                db.close()

    def _flush_task(self, task_id: int) -> None:
        """刷新指定任务的日志。"""
        if not self._buffer[task_id]:
            return

        from app.database import SessionLocal
        from app.models import TaskLog

        buffer_copy = self._buffer[task_id][:]
        self._buffer[task_id].clear()

        db = SessionLocal()
        should_close = "PYTEST_CURRENT_TEST" not in os.environ
        try:
            logs = [
                TaskLog(
                    task_id=task_id,
                    level=item["level"],
                    stage=item.get("stage"),
                    message=item["message"],
                )
                for item in buffer_copy
            ]
            db.add_all(logs)
            db.commit()
            logger.debug("批量写入任务日志: task_id=%d, count=%d", task_id, len(logs))
        except Exception as e:
            db.rollback()
            logger.warning("批量写入任务日志失败: %s", e)
        finally:
            if should_close:
                db.close()

    def flush_all(self) -> None:
        """刷新所有缓冲日志。"""
        with self._lock:
            for task_id in list(self._buffer.keys()):
                if self._buffer[task_id]:
                    self._flush_task(task_id)
            self._last_flush = time.time()

    def start_background_flush(self) -> None:
        """启动后台定期刷新任务。"""
        if self._running:
            return
        self._running = True

        def flush_loop():
            while self._running:
                time.sleep(self._flush_interval)
                self.flush_all()

        thread = threading.Thread(target=flush_loop, daemon=True)
        thread.start()

    def shutdown(self) -> None:
        """停止并刷新剩余数据。"""
        self._running = False
        self.flush_all()


# 全局任务日志缓冲区
_task_log_buffer = TaskLogBuffer()


class TaskService:
    """后台任务服务"""

    ACTIVE_STATUSES = ("pending", "running")
    FULL_TASK_TYPES = ("full_update", "tomorrow_star")
    SINGLE_ANALYSIS_TASK_TYPE = "single_analysis"
    GENERATE_HISTORY_TASK_TYPE = "generate_history"
    GENERATE_HISTORY_DETAIL_TASK_TYPE = "generate_history_detail"
    # 阶段6：历史回溯任务类型
    HISTORY_BACKFILL_INIT_TASK_TYPE = "history_backfill_initialize"
    HISTORY_BACKFILL_INCR_TASK_TYPE = "history_backfill_incremental"
    HISTORY_BACKFILL_BATCH_TASK_TYPE = "history_backfill_batch"
    _creation_lock = threading.Lock()
    _running_tasks: Dict[int, asyncio.subprocess.Process] = {}
    _cancelled_tasks: set[int] = set()

    # 全量更新步骤定义（断点续传支持）
    # 优化后的6阶段流程
    FULL_UPDATE_STEPS = [
        "data_preparing",   # 阶段1: 数据准备（评估 CSV + 回灌 + 增量更新）
        "build_pool",       # 阶段2: 量化初选
        "filter_candidates",# 阶段3: 候选筛选
        "score_analysis",   # 阶段4: 评分分析
        "export_results",   # 阶段5: 结果导出
        "completed",        # 阶段6: 完成
    ]

    STAGE_INFO = {
        # === 新的6阶段流程（优化后） ===
        "queued": {"label": "排队中", "index": 0, "total": 6, "percent": 0},
        "starting": {"label": "启动中", "index": 0, "total": 6, "percent": 0},
        "preparing": {"label": "准备中", "index": 0, "total": 6, "percent": 2},

        # 阶段1: 数据准备（15%）
        "data_preparing": {"label": "数据准备", "detail": "评估 CSV + 回灌数据库 + 增量更新", "index": 1, "total": 6, "percent": 15},
        "fetch_data": {"label": "数据准备", "detail": "增量/全量抓取数据", "index": 1, "total": 6, "percent": 15},  # 兼容旧名称
        "csv_import": {"label": "数据准备", "detail": "CSV 回灌中", "index": 1, "total": 6, "percent": 8},   # CSV 回灌子步骤

        # 阶段2: 量化初选（35%）
        "build_pool": {"label": "量化初选", "detail": "筛选流动性股票", "index": 2, "total": 6, "percent": 35},

        # 阶段3: 候选筛选（55%）
        "filter_candidates": {"label": "候选筛选", "detail": "导出候选图表", "index": 3, "total": 6, "percent": 55},
        "build_candidates": {"label": "候选筛选", "detail": "导出候选图表", "index": 3, "total": 6, "percent": 55},  # 兼容旧名称

        # 阶段4: 评分分析（75%）
        "score_analysis": {"label": "评分分析", "detail": "生成评分结果", "index": 4, "total": 6, "percent": 75},
        "pre_filter": {"label": "评分分析", "detail": "生成评分结果", "index": 4, "total": 6, "percent": 75},  # 兼容旧名称

        # 阶段5: 结果导出（90%）
        "export_results": {"label": "结果导出", "detail": "导出 PASS 图表", "index": 5, "total": 6, "percent": 90},
        "score_review": {"label": "结果导出", "detail": "导出 PASS 图表", "index": 5, "total": 6, "percent": 90},  # 兼容旧名称

        # 阶段6: 完成（100%）
        "finalize": {"label": "输出推荐", "detail": "生成最终结果", "index": 6, "total": 6, "percent": 100},
        "completed": {"label": "已完成", "detail": "全量初始化完成", "index": 6, "total": 6, "percent": 100},
        "failed": {"label": "执行失败", "index": 6, "total": 6, "percent": 100},
        "cancelled": {"label": "已取消", "index": 6, "total": 6, "percent": 100},

        # === 其他任务类型 ===
        "analysis": {"label": "单股分析", "index": 1, "total": 1, "percent": 50},
        "generating_history": {"label": "生成历史数据", "index": 1, "total": 2, "percent": 50},
        "generating_history_detail": {"label": "生成诊断详情", "index": 1, "total": 2, "percent": 50},

        # === 历史回溯阶段 ===
        "backfill_initializing": {"label": "初始化历史回溯", "index": 1, "total": 2, "percent": 10},
        "backfill_processing": {"label": "回溯处理中", "index": 2, "total": 2, "percent": 50},
    }

    def __init__(self, db: Session, manager=None):
        self.db = db
        self.running_tasks = self.__class__._running_tasks
        self.manager = manager

        # 确保后台刷新任务只启动一次
        if not _task_log_buffer._running:
            _task_log_buffer.start_background_flush()

    async def create_task(self, task_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建任务"""
        from app.models import Task

        with self._creation_lock:
            # 全量任务去重
            if task_type in self.FULL_TASK_TYPES:
                existing_task = self.get_active_full_task()
                if existing_task:
                    return {
                        "task_id": existing_task.id,
                        "ws_url": f"/ws/tasks/{existing_task.id}",
                        "existing": True,
                    }

            # 单股分析任务去重：检查同一股票、同一reviewer、同一交易日是否有进行中或已完成的任务
            if task_type == self.SINGLE_ANALYSIS_TASK_TYPE:
                code = params.get("code")
                reviewer = params.get("reviewer", "quant")
                if code:
                    existing_task = self._get_active_single_analysis_task(code, reviewer)
                    if existing_task:
                        return {
                            "task_id": existing_task.id,
                            "ws_url": f"/ws/tasks/{existing_task.id}",
                            "existing": True,
                        }

            # 历史生成任务去重：检查同一股票是否有进行中的历史生成任务
            if task_type == self.GENERATE_HISTORY_TASK_TYPE:
                code = params.get("code")
                if code:
                    existing_task = self._get_active_generate_history_task(code)
                    if existing_task:
                        return {
                            "task_id": existing_task.id,
                            "ws_url": f"/ws/tasks/{existing_task.id}",
                            "existing": True,
                        }
            if task_type == self.GENERATE_HISTORY_DETAIL_TASK_TYPE:
                code = params.get("code")
                check_date = params.get("check_date")
                if code and check_date:
                    existing_task = self._get_active_generate_history_detail_task(code, check_date)
                    if existing_task:
                        return {
                            "task_id": existing_task.id,
                            "ws_url": f"/ws/tasks/{existing_task.id}",
                            "existing": True,
                        }

            # 阶段6：历史回溯任务去重
            if task_type in (
                self.HISTORY_BACKFILL_INIT_TASK_TYPE,
                self.HISTORY_BACKFILL_INCR_TASK_TYPE,
            ):
                code = params.get("code")
                if code:
                    existing_task = self._get_active_backfill_task(code)
                    if existing_task:
                        return {
                            "task_id": existing_task.id,
                            "ws_url": f"/ws/tasks/{existing_task.id}",
                            "existing": True,
                        }

            task = Task(
                task_type=task_type,
                trigger_source=params.get("trigger_source", "manual"),
                status="pending",
                task_stage="queued",
                params_json=params,
                progress=0,
                progress_meta_json=self._build_stage_meta("queued", progress=0, message="任务已进入队列"),
                summary=self._build_summary(task_type, params),
            )
            self.db.add(task)
            self.db.commit()
            self.db.refresh(task)

        # 启动任务（后台执行）
        asyncio.create_task(self._run_task(task.id))

        return {
            "task_id": task.id,
            "ws_url": f"/ws/tasks/{task.id}",
            "existing": False,
        }

    def get_active_full_task(self) -> Optional[Any]:
        """返回当前活跃的全量类任务。"""
        from app.models import Task

        return (
            self.db.query(Task)
            .filter(
                Task.task_type.in_(self.FULL_TASK_TYPES),
                Task.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .first()
        )

    def _get_active_single_analysis_task(self, code: str, reviewer: str = "quant") -> Optional[Any]:
        """返回指定股票的活跃分析任务（pending/running）。

        用于防止重复创建同一股票的分析任务。业务键为：code + reviewer + analysis_date。
        仅复用同业务键的 pending/running 任务，已完成任务允许重新发起，以便在
        规则修复或数据更新后重新生成结果。

        Args:
            code: 股票代码
            reviewer: 评审者类型 (quant/glm/qwen/gemini)

        Returns:
            Task对象或None
        """
        from app.models import Task
        from datetime import timedelta, date

        # 优先复用同业务键的 pending/running 任务
        running_task = (
            self.db.query(Task)
            .filter(
                Task.task_type == self.SINGLE_ANALYSIS_TASK_TYPE,
                Task.filter_by_code(code),
                Task.params_json["reviewer"].as_string() == reviewer,
                Task.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .first()
        )
        if running_task:
            return running_task

        return None

    def _get_active_generate_history_task(self, code: str) -> Optional[Any]:
        """返回指定股票的活跃历史生成任务（pending/running）。

        阶段5新增：防止重复创建同一股票的历史生成任务。
        只复用同股票的 pending/running 任务，已完成任务允许重新发起。

        Args:
            code: 股票代码

        Returns:
            Task对象或None
        """
        from app.models import Task

        running_task = (
            self.db.query(Task)
            .filter(
                Task.task_type == self.GENERATE_HISTORY_TASK_TYPE,
                Task.filter_by_code(code),
                Task.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .first()
        )
        return running_task

    def _get_active_generate_history_detail_task(self, code: str, check_date: str) -> Optional[Any]:
        from app.models import Task

        return (
            self.db.query(Task)
            .filter(
                Task.task_type == self.GENERATE_HISTORY_DETAIL_TASK_TYPE,
                Task.filter_by_code(code),
                Task.params_json["check_date"].as_string() == check_date,
                Task.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .first()
        )

    async def _run_task(self, task_id: int):
        """运行任务"""
        from app.models import Task
        from app.database import SessionLocal

        db = SessionLocal()
        owns_session = db is not self.db
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            if owns_session:
                db.close()
            return

        # 保存 task_id, task_type, params_json 和 progress 以便后续使用，避免在 task 对象可能过期后访问
        saved_task_id = task.id
        task_type = task.task_type
        params_json = task.params_json or {}
        # 使用 task.progress 的初始值，避免在异常处理时访问可能过期的 task 对象
        initial_progress = 0
        task_started_monotonic = time.perf_counter()

        task.status = "running"
        task.started_at = utc_now()
        task.progress = 0
        task.task_stage = "starting"
        task.progress_meta_json = self._build_stage_meta("starting", progress=0, message="任务启动中")
        db.commit()
        # 关键状态变更立即记录
        self._record_task_log(task, "任务已启动", "info", immediate=True, task_id=saved_task_id, task_stage="starting")
        await self._publish_ops_task_event(task, "task_started")

        try:
            if task_type == "full_update":
                await self._run_full_update(task, db)
            elif task_type == "single_analysis":
                await self._run_single_analysis(task, db, params_json)
            elif task_type == "tomorrow_star":
                await self._run_tomorrow_star(task, db)
            elif task_type == "generate_history":
                await self._run_generate_history(task, db, params_json)
            elif task_type == self.GENERATE_HISTORY_DETAIL_TASK_TYPE:
                await self._run_generate_history_detail(task, db, params_json)
            # 阶段6：历史回溯任务
            elif task_type == self.HISTORY_BACKFILL_INIT_TASK_TYPE:
                await self._run_history_backfill_initialize(task, db, params_json)
            elif task_type == self.HISTORY_BACKFILL_INCR_TASK_TYPE:
                await self._run_history_backfill_incremental(task, db, params_json)
            elif task_type == self.HISTORY_BACKFILL_BATCH_TASK_TYPE:
                await self._run_history_backfill_batch(task, db, params_json)

            if saved_task_id in self._cancelled_tasks:
                raise asyncio.CancelledError()

            task.status = "completed"
            task.progress = 100
            task.task_stage = "completed"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("completed", progress=100, message="任务执行完成")
            task.result_json = self._append_runtime_metrics(task.result_json, task_started_monotonic)
            db.commit()
            self._record_task_log(task, "任务执行完成", "success", immediate=True, task_id=saved_task_id, task_stage="completed")
            await self._publish_ops_task_event(task, "task_completed")

        except asyncio.CancelledError:
            task.status = "cancelled"
            task.task_stage = "cancelled"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("cancelled", progress=task.progress, message="任务已取消")
            task.result_json = self._append_runtime_metrics(task.result_json, task_started_monotonic)
            db.commit()
            self._record_task_log(task, "任务已取消", "warning", immediate=True, task_id=saved_task_id, task_stage="cancelled")
            await self._publish_ops_task_event(task, "task_cancelled")
        except Exception as e:
            # 在异常处理中，task 对象可能已经过期，使用保存的值
            try:
                current_progress = task.progress
            except Exception:
                current_progress = initial_progress
            task.status = "failed"
            task.error_message = str(e)
            task.task_stage = "failed"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("failed", progress=current_progress, message=f"任务执行失败: {str(e)}")
            task.result_json = self._append_runtime_metrics(task.result_json, task_started_monotonic)
            db.commit()
            self._record_task_log(task, f"任务执行失败: {str(e)}", "error", immediate=True, task_id=saved_task_id, task_stage="failed")
            await self._publish_ops_task_event(task, "task_failed")

        finally:
            # 确保任务结束前刷新所有日志
            _task_log_buffer.flush_all()
            if saved_task_id in self.running_tasks:
                del self.running_tasks[saved_task_id]
            self._cancelled_tasks.discard(saved_task_id)
            # 仅关闭当前方法内部创建的 session，避免误关测试注入的共享 session。
            if owns_session:
                db.close()

    async def _run_full_update(self, task: Any, db: Session):
        """运行全量更新"""
        stage_started_at: dict[str, float] = {}
        stage_durations: dict[str, float] = {}
        last_marked_stage: Optional[str] = None  # 追踪上一个已标记的步骤

        def mark_stage(stage_name: Optional[str]) -> None:
            if not stage_name:
                return
            now = time.perf_counter()
            previous_stage = task.task_stage
            if previous_stage and previous_stage in stage_started_at:
                elapsed = now - stage_started_at[previous_stage]
                if math.isfinite(elapsed) and elapsed >= 0:
                    stage_durations[previous_stage] = round(elapsed, 3)
            stage_started_at[stage_name] = now

        params = task.params_json or {}
        reviewer = params.get("reviewer", "quant")
        skip_fetch = params.get("skip_fetch", False)
        start_from = params.get("start_from", 1)
        reset_derived_state = bool(params.get("reset_derived_state", False))
        task.task_stage = "preparing"
        task.progress_meta_json = self._build_stage_meta("preparing", progress=2, message="正在准备全量初始化任务")
        mark_stage("preparing")
        db.commit()

        # 检查是否为恢复执行，初始化 steps_completed
        if task.steps_completed is None:
            task.steps_completed = {}

        if reset_derived_state:
            self._reset_full_update_state(db, task)
            self._mark_step_completed(task, "resetting", db)
            task.progress_meta_json = self._build_stage_meta("preparing", progress=3, message="已重置数据库状态，准备重新执行全量初始化")
            db.commit()

        # 构建命令
        cmd = [
            sys.executable or "python",
            str(ROOT / "run_all.py"),
            "--reviewer", reviewer,
            "--db",  # 始终使用数据库模式存储 K 线数据
        ]

        if skip_fetch or start_from > 1:
            cmd.extend(["--start-from", str(start_from)])

        # 使用 asyncio.create_subprocess_exec 代替 subprocess.Popen
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        # 保存进程引用（用于取消）
        self.running_tasks[task.id] = process

        # 读取输出
        from app.websocket.utils import (
            is_progress_line,
            parse_log_type,
            parse_progress,
            parse_progress_payload,
            send_log,
        )

        # 阶段到步骤名称的映射
        stage_to_step = {
            "fetch_data": "fetch_data",
            "build_pool": "build_pool",
            "build_candidates": "build_candidates",
            "pre_filter": "pre_filter",
            "score_review": "score_review",
            "finalize": "finalize",
        }

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            line = line.decode(locale.getpreferredencoding(False), errors="replace").strip()

            if line:
                log_type = parse_log_type(line)
                # 通过 WebSocket 发送日志
                if self.manager:
                    await send_log(self.manager, task.id, line, log_type)
                else:
                    print(f"[Task {task.id}] {line}")

                stage = self._parse_stage(line)
                if stage and stage != task.task_stage:
                    mark_stage(stage)
                    task.task_stage = stage
                    task.progress_meta_json = self._build_stage_meta(stage, progress=task.progress, message=line)

                    # 标记步骤完成（断点续传支持）
                    step_name = stage_to_step.get(stage)
                    if step_name and step_name != last_marked_stage:
                        self._mark_step_completed(task, step_name, db)
                        last_marked_stage = step_name

                # 解析并更新进度
                progress = parse_progress(line)
                if progress is not None:
                    task.progress = progress
                progress_payload = parse_progress_payload(line)
                if progress_payload:
                    task.progress_meta_json = self._merge_progress_meta(task, progress_payload)
                    payload_stage = progress_payload.get("stage")
                    if payload_stage:
                        if str(payload_stage) != task.task_stage:
                            mark_stage(str(payload_stage))
                        task.task_stage = str(payload_stage)

                        # 检查是否为 CSV 回灌完成
                        if payload_stage == "fetch_data" and progress_payload.get("csv_imported_count"):
                            self._mark_step_completed(task, "csv_import", db)
                elif stage and (not task.progress_meta_json or task.progress_meta_json.get("stage") != stage):
                    task.progress_meta_json = self._build_stage_meta(stage, progress=task.progress, message=line)

                # 结构化进度行只更新状态，不写日志表（避免膨胀）
                # 非进度行使用缓冲区批量写入
                if not is_progress_line(line) and not _should_skip_task_log_line(line):
                    self._record_task_log(task, line, log_type, stage=stage)

                # 每处理100行输出提交一次状态，避免频繁写库
                db.commit()
                await self._publish_ops_task_event(task, "task_progress")

        # 等待进程完成
        return_code = await process.wait()

        if return_code != 0:
            if task.id in self._cancelled_tasks:
                raise asyncio.CancelledError()
            raise Exception(f"命令执行失败，返回码: {return_code}")

        # 保存结果
        from app.services.tushare_service import TushareService
        tushare_service = TushareService()
        # 清除数据状态缓存
        TushareService.clear_data_status_cache()

        # 清除管理员总览元数据缓存
        try:
            from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service
            metadata_service = get_admin_summary_metadata_service(db)
            metadata_service.invalidate()
        except Exception:
            pass  # 不影响主流程

        try:
            synced_count = tushare_service.sync_stock_list_to_db(db)
        except Exception as exc:
            synced_count = 0
            print(f"同步股票基础信息失败: {exc}")
        try:
            candidate_synced = self._sync_candidates_from_files(db)
        except Exception as exc:
            candidate_synced = 0
            print(f"同步候选结果失败: {exc}")
        try:
            analysis_synced = self._sync_analysis_results_from_files(db, reviewer=reviewer)
        except Exception as exc:
            analysis_synced = 0
            print(f"同步分析结果失败: {exc}")
        status = tushare_service.check_data_status()
        task.result_json = {
            "data_status": status,
            "stock_basic_synced": synced_count,
            "candidate_synced": candidate_synced,
            "analysis_synced": analysis_synced,
            "stage_metrics": {
                "durations_seconds": stage_durations,
            },
        }

    def _reset_full_update_state(self, db: Session, task: Any) -> None:
        """重置数据库中的全量初始化结果，但保留 CSV 原始文件供步骤 1 续跑。"""
        from app.cache import cache
        from app.models import (
            AnalysisResult,
            Candidate,
            DailyB1Check,
            DailyB1CheckDetail,
            StockAnalysis,
            StockDaily,
            TomorrowStarRun,
        )

        task.task_stage = "resetting"
        task.progress = 1
        self._record_task_log(task, "开始重置数据库中的 K 线、候选、分析与统计结果（保留 CSV 原始文件）", "warning", immediate=True, stage="resetting")

        db.query(AnalysisResult).delete(synchronize_session=False)
        db.query(Candidate).delete(synchronize_session=False)
        db.query(TomorrowStarRun).delete(synchronize_session=False)
        db.query(DailyB1CheckDetail).delete(synchronize_session=False)
        db.query(DailyB1Check).delete(synchronize_session=False)
        db.query(StockAnalysis).delete(synchronize_session=False)
        db.query(StockDaily).delete(synchronize_session=False)
        db.commit()

        cache.delete("data_status")
        cache.delete("running_tasks")
        self._record_task_log(task, "数据库派生状态已重置，后续将根据 CSV 与最新交易日重新评估抓取进度", "info", immediate=True, stage="resetting")

    async def _run_single_analysis(self, task: Any, db: Session, params_json: dict = None):
        """运行单股分析"""
        params = params_json or task.params_json or {}
        code = params.get("code")
        if not code:
            raise Exception("缺少股票代码")

        from app.services.analysis_service import analysis_service

        result = analysis_service.analyze_stock(code, params.get("reviewer", "quant"))
        task.result_json = result
        task.task_stage = "analysis"
        task.progress = 100
        task.progress_meta_json = self._build_stage_meta("analysis", progress=100, message=f"单股分析完成: {code}")

    async def _run_tomorrow_star(self, task: Any, db: Session):
        """生成明日之星"""
        # 相当于执行到步骤6的全量更新
        await self._run_full_update(task, db)

    async def _run_generate_history(self, task: Any, db: Session, params_json: dict = None):
        """运行历史数据生成任务

        阶段5新增：从 BackgroundTasks 改为 TaskService 统一管理。
        """
        params = params_json or task.params_json or {}
        code = params.get("code")
        if not code:
            raise Exception("缺少股票代码")

        days = params.get("days", 30)
        clean = params.get("clean", True)

        from app.services.analysis_service import analysis_service

        # 更新任务状态
        task.task_stage = "generating_history"
        task.progress = 10
        task.progress_meta_json = self._build_stage_meta(
            "generating_history",
            progress=10,
            message=f"开始生成 {code} 最近{days}个交易日的历史数据"
        )
        db.commit()

        # 执行历史数据生成（在异步上下文中运行同步函数）
        import asyncio
        result = await asyncio.to_thread(
            analysis_service.generate_stock_history_checks,
            code,
            days=days,
            clean=clean,
        )

        if not result.get("success"):
            raise Exception(result.get("error", "历史数据生成失败"))

        task.result_json = result
        task.task_stage = "completed"
        task.progress = 100
        task.progress_meta_json = self._build_stage_meta(
            "completed",
            progress=100,
            message=f"历史数据生成完成: {code}, 共{result.get('generated_count', 0)}条记录"
        )

    async def _run_generate_history_detail(self, task: Any, db: Session, params_json: dict = None):
        params = params_json or task.params_json or {}
        code = params.get("code")
        check_date = params.get("check_date")
        force = bool(params.get("force", False))
        if not code or not check_date:
            raise Exception("缺少股票代码或交易日")

        from app.services.analysis_service import analysis_service

        task.task_stage = "generating_history_detail"
        task.progress = 10
        task.progress_meta_json = self._build_stage_meta(
            "generating_history_detail",
            progress=10,
            message=f"开始生成 {code} {check_date} 的诊断详情",
        )
        db.commit()

        result = await asyncio.to_thread(
            analysis_service.generate_history_detail,
            code,
            check_date,
            force,
        )
        if not result.get("success"):
            raise Exception(result.get("error", "诊断详情生成失败"))

        task.result_json = result
        task.task_stage = "completed"
        task.progress = 100
        task.progress_meta_json = self._build_stage_meta(
            "completed",
            progress=100,
            message=f"诊断详情生成完成: {code} {check_date}",
        )

    async def _run_history_backfill_initialize(
        self, task: Any, db: Session, params_json: dict = None
    ):
        """运行历史回溯初始化任务（阶段6）

        初始化时补齐近一年历史数据。
        """
        params = params_json or task.params_json or {}
        code = params.get("code")
        if not code:
            raise Exception("缺少股票代码")

        from app.services.history_backfill_service import get_history_backfill_service

        # 更新任务状态
        task.task_stage = "backfill_initializing"
        task.progress = 5
        task.progress_meta_json = self._build_stage_meta(
            "backfill_initializing",
            progress=5,
            message=f"开始初始化 {code} 的历史回溯数据"
        )
        db.commit()

        # 执行历史回溯初始化
        service = get_history_backfill_service()

        def progress_callback(progress_info: dict):
            """进度回调"""
            current_progress = 5 + int(progress_info.get("progress_pct", 0) * 0.9)
            task.progress = min(95, current_progress)
            task.progress_meta_json = self._build_stage_meta(
                "backfill_processing",
                progress=task.progress,
                message=f"回溯处理中: {progress_info.get('current_date', '')} ({progress_info.get('completed', 0)}/{progress_info.get('total', 0)})"
            )
            db.commit()

        result = await asyncio.to_thread(
            service.initialize_year_history,
            code,
            progress_callback=progress_callback,
        )

        task.result_json = result.to_dict()
        task.task_stage = "completed"
        task.progress = 100
        task.progress_meta_json = self._build_stage_meta(
            "completed",
            progress=100,
            message=f"历史回溯初始化完成: {code}, 共{result.backfilled_days}天"
        )

    async def _run_history_backfill_incremental(
        self, task: Any, db: Session, params_json: dict = None
    ):
        """运行增量历史回溯任务（阶段6）

        只补齐最新交易日的历史记录，不重复回算已有历史。
        """
        params = params_json or task.params_json or {}
        code = params.get("code")
        if not code:
            raise Exception("缺少股票代码")

        from app.services.history_backfill_service import get_history_backfill_service

        # 更新任务状态
        task.task_stage = "backfill_processing"
        task.progress = 10
        task.progress_meta_json = self._build_stage_meta(
            "backfill_processing",
            progress=10,
            message=f"开始增量补齐 {code} 的最新交易日"
        )
        db.commit()

        # 执行增量历史回溯
        service = get_history_backfill_service()
        result = await asyncio.to_thread(
            service.incremental_backfill_latest_trade_date,
            code,
        )

        # 清除相关缓存
        TushareService.clear_data_status_cache()
        try:
            from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service
            metadata_service = get_admin_summary_metadata_service(db)
            metadata_service.invalidate()
        except Exception:
            pass  # 不影响主流程

        task.result_json = result.to_dict()
        task.task_stage = "completed"
        task.progress = 100
        task.progress_meta_json = self._build_stage_meta(
            "completed",
            progress=100,
            message=f"增量历史回溯完成: {code}, 最新日期 {result.latest_date}"
        )

    async def _run_history_backfill_batch(
        self, task: Any, db: Session, params_json: dict = None
    ):
        """运行批量历史回溯任务（阶段6）

        批量补齐多只股票的历史数据。
        """
        params = params_json or task.params_json or {}
        codes = params.get("codes", [])
        if not codes:
            raise Exception("缺少股票代码列表")

        target_date = params.get("target_date")

        from app.services.history_backfill_service import get_history_backfill_service

        # 更新任务状态
        task.task_stage = "backfill_initializing"
        task.progress = 5
        task.progress_meta_json = self._build_stage_meta(
            "backfill_initializing",
            progress=5,
            message=f"开始批量历史回溯 ({len(codes)} 只股票)"
        )
        db.commit()

        # 执行批量历史回溯
        service = get_history_backfill_service()

        def progress_callback(progress_info: dict):
            """进度回调"""
            current_progress = 5 + int(progress_info.get("progress_pct", 0) * 0.9)
            task.progress = min(95, current_progress)
            task.progress_meta_json = self._build_stage_meta(
                "backfill_processing",
                progress=task.progress,
                message=f"批量处理中: {progress_info.get('current_code', '')} ({progress_info.get('completed', 0)}/{progress_info.get('total', 0)})"
            )
            db.commit()

        result = await asyncio.to_thread(
            service.backfill_multiple_stocks,
            codes,
            target_date=target_date,
            progress_callback=progress_callback,
        )

        # 清除相关缓存
        TushareService.clear_data_status_cache()
        try:
            from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service
            metadata_service = get_admin_summary_metadata_service(db)
            metadata_service.invalidate()
        except Exception:
            pass  # 不影响主流程

        task.result_json = result
        task.task_stage = "completed"
        task.progress = 100
        task.progress_meta_json = self._build_stage_meta(
            "completed",
            progress=100,
            message=f"批量历史回溯完成: {result.get('completed', 0)} 成功, {result.get('failed', 0)} 失败"
        )

    def _get_active_backfill_task(self, code: str) -> Optional[Any]:
        """返回指定股票的活跃历史回溯任务（pending/running）。

        阶段6新增：防止重复创建同一股票的历史回溯任务。
        只复用同股票的 pending/running 任务，已完成任务允许重新发起。

        Args:
            code: 股票代码

        Returns:
            Task对象或None
        """
        from app.models import Task

        running_task = (
            self.db.query(Task)
            .filter(
                Task.task_type.in_([
                    self.HISTORY_BACKFILL_INIT_TASK_TYPE,
                    self.HISTORY_BACKFILL_INCR_TASK_TYPE,
                ]),
                Task.filter_by_code(code),
                Task.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .first()
        )
        return running_task

    def is_task_process_alive(self, task_id: int) -> bool:
        """判断任务对应的子进程是否仍然存活。"""
        process = self.running_tasks.get(task_id)
        if process is None:
            return False
        return process.returncode is None

    async def cancel_task(self, task_id: int) -> bool:
        """取消任务"""
        if task_id in self.running_tasks:
            process = self.running_tasks[task_id]
            self._cancelled_tasks.add(task_id)
            try:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            except Exception as e:
                print(f"Error cancelling task {task_id}: {e}")
            return True
        return False

    def get_task_status(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        from app.models import Task
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if task:
                return {
                    "id": task.id,
                    "task_type": task.task_type,
                    "trigger_source": task.trigger_source,
                    "status": task.status,
                    "task_stage": task.task_stage,
                    "progress": task.progress,
                    "progress_meta_json": task.progress_meta_json,
                    "result": task.result_json,
                    "error": task.error_message
                }
            return None
        finally:
            db.close()

    async def _publish_ops_task_event(self, task: Any, event_type: str) -> None:
        if not self.manager:
            return
        from app.websocket.utils import send_ops_event

        await send_ops_event(
            self.manager,
            event_type,
            {
                "id": task.id,
                "task_type": task.task_type,
                "trigger_source": task.trigger_source,
                "status": task.status,
                "task_stage": task.task_stage,
                "progress": task.progress,
                "progress_meta_json": task.progress_meta_json,
                "summary": task.summary,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "error_message": task.error_message,
            },
        )

    @staticmethod
    def _build_summary(task_type: str, params: Dict[str, Any]) -> str:
        if task_type == "full_update":
            reviewer = params.get("reviewer", "quant")
            start_from = params.get("start_from", 1)
            skip_fetch = params.get("skip_fetch", False)
            parts = [f"全量更新 / reviewer={reviewer}", f"start_from={start_from}"]
            if skip_fetch:
                parts.append("skip_fetch")
            return " | ".join(parts)
        if task_type == "single_analysis":
            return f"单股分析 / code={params.get('code', '-')}"
        if task_type == "tomorrow_star":
            return f"明日之星生成 / reviewer={params.get('reviewer', 'quant')}"
        if task_type == "generate_history":
            return f"历史数据生成 / code={params.get('code', '-')}, days={params.get('days', 30)}"
        if task_type == "generate_history_detail":
            return f"诊断详情生成 / code={params.get('code', '-')}, check_date={params.get('check_date', '-')}"
        # 阶段6：历史回溯任务
        if task_type == "history_backfill_initialize":
            return f"历史回溯初始化 / code={params.get('code', '-')}"
        if task_type == "history_backfill_incremental":
            return f"增量历史回溯 / code={params.get('code', '-')}"
        if task_type == "history_backfill_batch":
            codes = params.get('codes', [])
            return f"批量历史回溯 / {len(codes)} 只股票"
        return task_type

    @staticmethod
    def _parse_stage(line: str) -> Optional[str]:
        line_lower = line.lower()
        if "步骤 1" in line or "step 1" in line_lower:
            return "fetch_data"
        if "步骤 2" in line or "step 2" in line_lower:
            return "build_pool"
        if "步骤 3" in line or "step 3" in line_lower:
            return "build_candidates"
        if "步骤 4" in line or "step 4" in line_lower:
            return "pre_filter"
        if "步骤 5" in line or "step 5" in line_lower:
            return "score_review"
        if "步骤 6" in line or "step 6" in line_lower:
            return "finalize"
        if "推荐" in line or "recommend" in line_lower:
            return "finalize"
        return None

    @staticmethod
    def _load_json_file(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def _sync_candidates_from_files(self, db: Session) -> int:
        from app.config import settings
        from app.models import Candidate
        from app.services.tushare_service import TushareService

        latest_file = settings.candidates_dir / "candidates_latest.json"
        if not latest_file.exists():
            return 0

        data = self._load_json_file(latest_file)
        pick_date_text = str(data.get("pick_date") or "").strip()
        if not pick_date_text:
            return 0

        items = data.get("candidates") or []
        if not isinstance(items, list):
            return 0

        pick_date = date.fromisoformat(pick_date_text)
        codes = [str(item.get("code", "")).zfill(6) for item in items if str(item.get("code", "")).strip()]
        if codes:
            TushareService().sync_stock_names_to_db(db, codes)

        db.query(Candidate).filter(Candidate.pick_date == pick_date).delete(synchronize_session=False)

        rows: list[Candidate] = []
        for item in items:
            code = str(item.get("code", "")).zfill(6)
            if not code or code == "000000":
                continue
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            rows.append(
                Candidate(
                    pick_date=pick_date,
                    code=code,
                    strategy=item.get("strategy"),
                    close_price=float(item["close"]) if item.get("close") is not None else None,
                    turnover=float(item["turnover_n"]) if item.get("turnover_n") is not None else None,
                    b1_passed=item.get("strategy") == "b1",
                    kdj_j=float(extra["kdj_j"]) if extra.get("kdj_j") is not None else None,
                )
            )

        if rows:
            db.add_all(rows)
            db.commit()
        return len(rows)

    def _sync_analysis_results_from_files(self, db: Session, reviewer: str = "quant") -> int:
        from app.config import settings
        from app.models import AnalysisResult
        from app.services.analysis_service import analysis_service
        from app.services.tushare_service import TushareService

        pick_date_text = analysis_service.get_latest_candidate_date()
        if not pick_date_text:
            return 0

        review_dir = settings.review_dir / pick_date_text
        if not review_dir.exists():
            return 0

        pick_date = date.fromisoformat(pick_date_text)
        stock_files = sorted(
            p for p in review_dir.glob("*.json")
            if p.name != "suggestion.json"
        )
        if not stock_files:
            return 0

        codes = [p.stem.zfill(6) for p in stock_files if p.stem.isdigit()]
        if codes:
            TushareService().sync_stock_names_to_db(db, codes)

        db.query(AnalysisResult).filter(AnalysisResult.pick_date == pick_date).delete(synchronize_session=False)

        rows: list[AnalysisResult] = []
        for path in stock_files:
            payload = self._load_json_file(path)
            code = str(payload.get("code") or path.stem).zfill(6)
            if not code or code == "000000":
                continue
            rows.append(
                AnalysisResult(
                    pick_date=pick_date,
                    code=code,
                    reviewer=reviewer,
                    verdict=payload.get("verdict"),
                    total_score=float(payload["total_score"]) if payload.get("total_score") is not None else None,
                    signal_type=payload.get("signal_type"),
                    comment=payload.get("comment"),
                    details_json=payload,
                )
            )

        if rows:
            db.add_all(rows)
            db.commit()
        return len(rows)

    @classmethod
    def _build_stage_meta(
        cls,
        stage: str,
        progress: Optional[int] = None,
        message: Optional[str] = None,
    ) -> dict[str, Any]:
        info = cls.STAGE_INFO.get(stage, {})
        percent = progress if progress is not None else int(info.get("percent", 0))
        return {
            "kind": "stage",
            "stage": stage,
            "stage_label": info.get("label", stage),
            "stage_index": info.get("index"),
            "stage_total": info.get("total"),
            "percent": max(0, min(100, int(percent))),
            "message": message or info.get("label", stage),
            "eta_seconds": None,
            "current": None,
            "total": None,
            "current_code": None,
        }

    @classmethod
    def _merge_progress_meta(cls, task: Any, payload: dict[str, Any]) -> dict[str, Any]:
        stage = str(payload.get("stage") or task.task_stage or "starting")
        meta = cls._build_stage_meta(stage, progress=payload.get("percent"), message=payload.get("message"))
        meta.update(payload)
        if meta.get("stage_label") in (None, ""):
            meta["stage_label"] = cls.STAGE_INFO.get(stage, {}).get("label", stage)
        if meta.get("percent") is None:
            meta["percent"] = task.progress
        return meta

    @staticmethod
    def _record_task_log(task: Any, message: str, level: str, stage: Optional[str] = None, immediate: bool = False, task_id: int = None, task_stage: str = None) -> None:
        """记录任务日志到缓冲区。

        Args:
            task: 任务对象（可选，如果提供则从中获取 task_id 和 task_stage）
            message: 日志消息
            level: 日志级别
            stage: 任务阶段（优先使用此值，其次使用 task_stage 参数，最后使用 task.task_stage）
            immediate: 是否立即写入（关键状态变更使用）
            task_id: 任务ID（如果 task 对象可能过期，则使用此参数）
            task_stage: 任务阶段（如果 task 对象可能过期，则使用此参数）
        """
        # 如果提供了 task_id，使用它；否则尝试从 task 对象获取
        tid = task_id if task_id is not None else (task.id if task is not None else None)
        # 确定使用的 stage 值
        used_stage = stage or task_stage or (task.task_stage if task is not None else None)

        _task_log_buffer.add(
            task_id=tid,
            level=level,
            message=message,
            stage=used_stage,
            immediate=immediate,
        )

    @staticmethod
    def _append_runtime_metrics(result_json: Optional[dict[str, Any]], started_at_monotonic: float) -> dict[str, Any]:
        payload = dict(result_json or {})
        elapsed = time.perf_counter() - started_at_monotonic
        if math.isfinite(elapsed) and elapsed >= 0:
            payload["runtime_metrics"] = {
                "total_seconds": round(elapsed, 3),
            }
        return payload

    def _mark_step_completed(self, task: Any, step_name: str, db: Session) -> None:
        """标记步骤为已完成。

        Args:
            task: 任务对象
            step_name: 步骤名称
            db: 数据库会话
        """
        if task.steps_completed is None:
            task.steps_completed = {}
        task.steps_completed[step_name] = True
        db.commit()
        self._record_task_log(task, f"步骤 '{step_name}' 已标记为完成", "info", stage=step_name, immediate=True)

    def _get_next_step(self, task: Any) -> Optional[str]:
        """获取下一个需要执行的步骤。

        Args:
            task: 任务对象

        Returns:
            下一个步骤名称，如果所有步骤已完成则返回 None
        """
        steps_completed = task.steps_completed or {}
        for step in self.FULL_UPDATE_STEPS:
            if not steps_completed.get(step, False):
                return step
        return None

    def _get_step_start_from(self, task: Any) -> int:
        """根据已完成的步骤计算 start_from 参数。

        Args:
            task: 任务对象

        Returns:
            start_from 步骤编号 (1-6)
        """
        steps_completed = task.steps_completed or {}

        # 步骤映射到 run_all.py 的 start_from 参数
        step_to_start_from = {
            "resetting": 1,
            "fetch_data": 1,
            "csv_import": 1,
            "build_pool": 2,
            "build_candidates": 3,
            "pre_filter": 4,
            "score_review": 5,
            "finalize": 6,
        }

        # 找到第一个未完成的步骤
        for step in self.FULL_UPDATE_STEPS:
            if not steps_completed.get(step, False):
                return step_to_start_from.get(step, 1)

        # 所有步骤都已完成，返回 6
        return 6

    def can_resume_task(self, task: Any) -> bool:
        """检查任务是否可以恢复执行。

        Args:
            task: 任务对象

        Returns:
            是否可以恢复
        """
        if task.status not in ("failed", "cancelled"):
            return False
        if task.task_type not in self.FULL_TASK_TYPES:
            return False
        # 检查是否有未完成的步骤
        steps_completed = task.steps_completed or {}
        for step in self.FULL_UPDATE_STEPS:
            if not steps_completed.get(step, False):
                return True
        return False

    def get_resume_info(self, task: Any) -> dict[str, Any]:
        """获取任务恢复信息。

        Args:
            task: 任务对象

        Returns:
            恢复信息字典
        """
        steps_completed = task.steps_completed or {}
        completed_steps = [step for step in self.FULL_UPDATE_STEPS if steps_completed.get(step, False)]
        next_step = self._get_next_step(task)
        start_from = self._get_step_start_from(task)

        step_labels = {
            "resetting": "重置数据库",
            "fetch_data": "拉取 K 线数据",
            "csv_import": "CSV 回灌",
            "build_pool": "量化初选",
            "build_candidates": "导出候选图表",
            "pre_filter": "生成评分结果",
            "score_review": "导出 PASS 图表",
            "finalize": "输出推荐结果",
        }

        return {
            "task_id": task.id,
            "can_resume": self.can_resume_task(task),
            "completed_steps": completed_steps,
            "completed_step_labels": [step_labels.get(s, s) for s in completed_steps],
            "next_step": next_step,
            "next_step_label": step_labels.get(next_step, next_step) if next_step else None,
            "start_from": start_from,
            "total_steps": len(self.FULL_UPDATE_STEPS),
            "progress_percent": int(len(completed_steps) / len(self.FULL_UPDATE_STEPS) * 100) if self.FULL_UPDATE_STEPS else 0,
        }


def flush_task_log_buffer() -> None:
    """手动刷新任务日志缓冲区（用于测试或优雅关闭）。"""
    _task_log_buffer.flush_all()
