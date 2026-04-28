"""
Task Service
~~~~~~~~~~~~
后台任务服务，集成 run_all.py
"""
import asyncio
import locale
import sys
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.time_utils import utc_now

ROOT = Path(__file__).parent.parent.parent.parent


class TaskService:
    """后台任务服务"""

    ACTIVE_STATUSES = ("pending", "running")
    FULL_TASK_TYPES = ("full_update", "tomorrow_star")
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

    async def create_task(self, task_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建任务"""
        from app.models import Task

        with self._creation_lock:
            if task_type in self.FULL_TASK_TYPES:
                existing_task = self.get_active_full_task()
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

    async def _run_task(self, task_id: int):
        """运行任务"""
        from app.models import Task
        from app.database import SessionLocal

        db = SessionLocal()
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        task.status = "running"
        task.started_at = utc_now()
        task.progress = 0
        task.task_stage = "starting"
        task.progress_meta_json = self._build_stage_meta("starting", progress=0, message="任务启动中")
        db.commit()
        self._record_task_log(db, task, "任务已启动", "info")
        await self._publish_ops_task_event(task, "task_started")

        try:
            if task.task_type == "full_update":
                await self._run_full_update(task, db)
            elif task.task_type == "single_analysis":
                await self._run_single_analysis(task, db)
            elif task.task_type == "tomorrow_star":
                await self._run_tomorrow_star(task, db)

            if task_id in self._cancelled_tasks:
                raise asyncio.CancelledError()

            task.status = "completed"
            task.progress = 100
            task.task_stage = "completed"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("completed", progress=100, message="任务执行完成")
            self._record_task_log(db, task, "任务执行完成", "success")
            await self._publish_ops_task_event(task, "task_completed")

        except asyncio.CancelledError:
            task.status = "cancelled"
            task.task_stage = "cancelled"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("cancelled", progress=task.progress, message="任务已取消")
            self._record_task_log(db, task, "任务已取消", "warning")
            await self._publish_ops_task_event(task, "task_cancelled")
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.task_stage = "failed"
            task.completed_at = utc_now()
            task.progress_meta_json = self._build_stage_meta("failed", progress=task.progress, message=f"任务执行失败: {str(e)}")
            self._record_task_log(db, task, f"任务执行失败: {str(e)}", "error")
            await self._publish_ops_task_event(task, "task_failed")

        finally:
            db.commit()
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
            self._cancelled_tasks.discard(task_id)

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
            "--reviewer", reviewer
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
                if not is_progress_line(line):
                    self._record_task_log(db, task, line, log_type, stage=stage)
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
        status = tushare_service.check_data_status()
        task.result_json = {
            "data_status": status,
            "stock_basic_synced": synced_count,
        }

    async def _run_single_analysis(self, task: Any, db: Session):
        """运行单股分析"""
        params = task.params_json or {}
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
    def _record_task_log(db: Session, task: Any, message: str, level: str, stage: Optional[str] = None) -> None:
        from app.models import TaskLog

        log = TaskLog(
            task_id=task.id,
            level=level,
            stage=stage or task.task_stage,
            message=message,
        )
        db.add(log)
