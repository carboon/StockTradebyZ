"""
Task Service
~~~~~~~~~~~~
后台任务服务，集成 run_all.py 及智能数据同步逻辑
"""
import asyncio
import json
import locale
import os
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

ROOT = Path(__file__).parent.parent.parent.parent

# 北京时间时区 (UTC+8)
from app.models import beijing_now


class TaskService:
    """后台任务服务"""

    def __init__(self, db: Session, manager=None):
        self.db = db
        self.running_tasks: Dict[int, subprocess.Popen] = {}
        self.manager = manager

    async def create_task(self, task_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """创建任务"""
        from app.models import Task

        task = Task(
            task_type=task_type,
            trigger_source=params.get("trigger_source", "manual"),
            status="pending",
            task_stage="queued",
            params_json=params,
            progress=0,
            summary=self._build_summary(task_type, params),
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)

        # 启动任务（后台执行）
        asyncio.create_task(self._run_task(task.id))

        return {
            "task_id": task.id,
            "ws_url": f"/ws/tasks/{task.id}"
        }

    async def _run_task(self, task_id: int):
        """运行任务"""
        from app.models import Task
        from app.database import SessionLocal

        db = SessionLocal()
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return

        task.status = "running"
        task.started_at = beijing_now()
        task.progress = 0
        task.task_stage = "starting"
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

            task.status = "completed"
            task.progress = 100
            task.task_stage = "completed"
            task.completed_at = beijing_now()
            self._record_task_log(db, task, "任务执行完成", "success")
            await self._publish_ops_task_event(task, "task_completed")

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.task_stage = "failed"
            task.completed_at = beijing_now()
            self._record_task_log(db, task, f"任务执行失败: {str(e)}", "error")
            await self._publish_ops_task_event(task, "task_failed")

        finally:
            db.commit()
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]

    async def _run_full_update(self, task: Any, db: Session):
        """运行全量更新"""
        params = task.params_json or {}
        reviewer = params.get("reviewer", "quant")
        skip_fetch = params.get("skip_fetch", False)
        start_from = params.get("start_from", 1)
        task.task_stage = "preparing"
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
        from app.websocket.utils import send_log, parse_progress, parse_log_type

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
                # 解析并更新进度
                progress = parse_progress(line)
                if progress is not None:
                    task.progress = progress
                self._record_task_log(db, task, line, log_type, stage=stage)
                db.commit()
                await self._publish_ops_task_event(task, "task_progress")

        # 等待进程完成
        return_code = await process.wait()

        if return_code != 0:
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

    async def _run_tomorrow_star(self, task: Any, db: Session):
        """生成明日之星"""
        # 相当于执行到步骤6的全量更新
        await self._run_full_update(task, db)

    async def cancel_task(self, task_id: int) -> bool:
        """取消任务"""
        if task_id in self.running_tasks:
            process = self.running_tasks[task_id]
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
    def _record_task_log(db: Session, task: Any, message: str, level: str, stage: Optional[str] = None) -> None:
        from app.models import TaskLog

        log = TaskLog(
            task_id=task.id,
            level=level,
            stage=stage or task.task_stage,
            message=message,
        )
        db.add(log)


def trigger_data_sync_task():
    """对外暴露的触发接口：启动后台线程执行智能同步"""
    thread = threading.Thread(target=_run_smart_sync, daemon=True)
    thread.start()

def _run_smart_sync():
    """后台线程执行的智能同步逻辑"""
    from app.services.market_service import market_service
    from app.services.tushare_service import TushareService
    from pipeline.fetch_kline import fetch_one_incremental, load_codes_from_stocklist
    
    ts_service = TushareService()
    ms = market_service
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. 获取网络时间和远程最新交易日
        now_beijing = ms.get_network_time_beijing()
        remote_date_str = ms.get_latest_trade_date() # 格式 YYYY-MM-DD
        
        if not remote_date_str:
            print("[Sync Task] Failed to get remote trade date.")
            return

        remote_date_yyyymmdd = remote_date_str.replace("-", "")
        local_status = ms._load_status()
        local_date_str = local_status.get("last_trade_date")
        
        stocklist_path = ROOT / "pipeline" / "stocklist.csv"
        codes = load_codes_from_stocklist(stocklist_path) if stocklist_path.exists() else []
        total_stocks = len(codes)
        
        print(f"[Sync Task] Network Time: {now_beijing}, Remote: {remote_date_str}, Local: {local_date_str}")

        # 辅助函数：更新进度
        def update_progress(current, total, msg):
            status = ms._load_status()
            status["progress"] = {"current": current, "total": total}
            status["message"] = msg
            ms._save_status(status)

        # 2. 逻辑分支
        if not codes:
            print("[Sync Task] No stocks found in stocklist.csv")
            return

        if not local_date_str:
            print("[Sync Task] No local data. Starting FULL update...")
            update_progress(0, total_stocks * 2, "正在全量初始化数据 (1/2)...")
            # 简化全量：只拉取最近一年
            for i, code in enumerate(codes):
                fetch_one_incremental(code, "20230101", remote_date_yyyymmdd, raw_dir)
                if i % 50 == 0: update_progress(i, total_stocks, f"全量初始化中... ({i}/{total_stocks})")
            update_progress(total_stocks, total_stocks, "全量初始化完成")
            
        elif local_date_str < remote_date_str:
            print(f"[Sync Task] Data missing. Incremental update...")
            update_progress(0, total_stocks, "正在补齐缺失的历史数据...")
            start_dt = datetime.strptime(local_date_str, "%Y-%m-%d") + timedelta(days=1)
            end_dt = datetime.strptime(remote_date_str, "%Y-%m-%d")
            
            current_dt = start_dt
            day_count = 0
            while current_dt <= end_dt:
                date_str = current_dt.strftime("%Y%m%d")
                day_count += 1
                update_progress(day_count - 1, (end_dt - start_dt).days + 1, f"正在补齐 {date_str} 的数据...")
                for code in codes:
                    fetch_one_incremental(code, date_str, date_str, raw_dir)
                current_dt += timedelta(days=1)
                
        elif now_beijing.hour >= 16:
            print("[Sync Task] After 16:00, checking today's data...")
            sample_df = ts_service.get_daily_data("000001.SZ", remote_date_yyyymmdd, remote_date_yyyymmdd)
            
            if sample_df is not None and not sample_df.empty:
                print("[Sync Task] Today's data available. Updating...")
                update_progress(0, total_stocks, "正在更新今日最新行情...")
                for i, code in enumerate(codes):
                    fetch_one_incremental(code, remote_date_yyyymmdd, remote_date_yyyymmdd, raw_dir)
                    if i % 100 == 0: update_progress(i, total_stocks, f"更新今日数据中... ({i}/{total_stocks})")
                update_progress(total_stocks, total_stocks, "今日数据更新完成")
            else:
                print("[Sync Task] Today's data not yet published.")
                update_progress(0, 0, "今日数据尚未发布，无需更新")
                
        else:
            print("[Sync Task] Before 16:00, no update needed.")
            update_progress(0, 0, "当前未到数据更新时间 (16:00后)")

        # 3. 更新最终状态
        status = ms._load_status()
        status["is_updating"] = False
        status["last_trade_date"] = remote_date_str
        status["update_type"] = None
        status["message"] = "数据已是最新"
        ms._save_status(status)
        print("[Sync Task] Completed successfully.")

    except Exception as e:
        print(f"[Sync Task] Error: {e}")
        import traceback
        traceback.print_exc()
        status = ms._load_status()
        status["is_updating"] = False
        status["message"] = f"更新失败: {str(e)}"
        ms._save_status(status)
