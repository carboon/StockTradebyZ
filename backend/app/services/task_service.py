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
    _creation_lock = threading.Lock()
    _running_tasks: Dict[int, asyncio.subprocess.Process] = {}
    _cancelled_tasks: set[int] = set()
    STAGE_INFO = {
        "queued": {"label": "排队中", "index": 0, "total": 6, "percent": 0},
        "starting": {"label": "启动中", "index": 0, "total": 6, "percent": 0},
        "preparing": {"label": "准备中", "index": 0, "total": 6, "percent": 2},
        "fetch_data": {"label": "抓取原始数据", "index": 1, "total": 6, "percent": 10},
        "build_pool": {"label": "量化初选", "index": 2, "total": 6, "percent": 35},
        "build_candidates": {"label": "导出候选图表", "index": 3, "total": 6, "percent": 55},
        "pre_filter": {"label": "生成评分结果", "index": 4, "total": 6, "percent": 72},
        "score_review": {"label": "导出 PASS 图表", "index": 5, "total": 6, "percent": 88},
        "finalize": {"label": "输出推荐结果", "index": 6, "total": 6, "percent": 96},
        "analysis": {"label": "单股分析", "index": 1, "total": 1, "percent": 100},
        "completed": {"label": "已完成", "index": 6, "total": 6, "percent": 100},
        "failed": {"label": "执行失败", "index": 6, "total": 6, "percent": 100},
        "cancelled": {"label": "已取消", "index": 6, "total": 6, "percent": 100},
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

            if saved_task_id in self._cancelled_tasks:
                raise asyncio.CancelledError()

            task.status = "completed"
            task.progress = 100
            task.task_stage = "completed"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("completed", progress=100, message="任务执行完成")
            db.commit()
            self._record_task_log(task, "任务执行完成", "success", immediate=True, task_id=saved_task_id, task_stage="completed")
            await self._publish_ops_task_event(task, "task_completed")

        except asyncio.CancelledError:
            task.status = "cancelled"
            task.task_stage = "cancelled"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("cancelled", progress=task.progress, message="任务已取消")
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
        params = task.params_json or {}
        reviewer = params.get("reviewer", "quant")
        skip_fetch = params.get("skip_fetch", False)
        start_from = params.get("start_from", 1)
        task.task_stage = "preparing"
        task.progress_meta_json = self._build_stage_meta("preparing", progress=2, message="正在准备全量初始化任务")
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
                    task.task_stage = stage
                    task.progress_meta_json = self._build_stage_meta(stage, progress=task.progress, message=line)
                # 解析并更新进度
                progress = parse_progress(line)
                if progress is not None:
                    task.progress = progress
                progress_payload = parse_progress_payload(line)
                if progress_payload:
                    task.progress_meta_json = self._merge_progress_meta(task, progress_payload)
                    payload_stage = progress_payload.get("stage")
                    if payload_stage:
                        task.task_stage = str(payload_stage)
                elif stage and (not task.progress_meta_json or task.progress_meta_json.get("stage") != stage):
                    task.progress_meta_json = self._build_stage_meta(stage, progress=task.progress, message=line)

                # 结构化进度行只更新状态，不写日志表（避免膨胀）
                # 非进度行使用缓冲区批量写入
                if not is_progress_line(line):
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
        }

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


def flush_task_log_buffer() -> None:
    """手动刷新任务日志缓冲区（用于测试或优雅关闭）。"""
    _task_log_buffer.flush_all()
