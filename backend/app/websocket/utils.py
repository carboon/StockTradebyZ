"""
WebSocket 工具函数
~~~~~~~~~~~~~~~~~~
提供 WebSocket 日志推送和进度解析功能
"""
import re
from datetime import datetime
from typing import Optional


async def send_log(manager, task_id: int, message: str, log_type: str = "info"):
    """
    发送日志到 WebSocket

    Args:
        manager: ConnectionManager 实例
        task_id: 任务 ID
        message: 日志消息
        log_type: 日志类型 (info, warning, error, success)
    """
    import json

    payload = json.dumps({
        "type": "log",
        "task_id": task_id,
        "message": message,
        "log_type": log_type,
        "timestamp": datetime.now().isoformat()
    }, ensure_ascii=False)

    await manager.send_message(task_id, payload)


async def send_ops_event(manager, event_type: str, payload: dict):
    """
    发送任务中心事件到统一运维频道。
    """
    import json

    message = json.dumps({
        "type": event_type,
        "payload": payload,
        "timestamp": datetime.now().isoformat(),
    }, ensure_ascii=False)

    await manager.send_message("ops", message)


def parse_progress(line: str) -> Optional[int]:
    """
    从日志行解析进度百分比

    Args:
        line: 日志行

    Returns:
        进度百分比 (0-100)，如果无法解析则返回 None
    """
    line_lower = line.lower()

    # 步骤匹配
    if "步骤 1" in line or "step 1" in line_lower:
        return 10
    elif "步骤 2" in line or "step 2" in line_lower:
        return 30
    elif "步骤 3" in line or "step 3" in line_lower:
        return 50
    elif "步骤 4" in line or "step 4" in line_lower:
        return 70
    elif "步骤 5" in line or "step 5" in line_lower:
        return 90
    elif "步骤 6" in line or "step 6" in line_lower or "推荐" in line or "recommend" in line_lower:
        return 100

    # 进度百分比匹配 (如 "进度: 50%" 或 "[=====>     ] 50%")
    progress_match = re.search(r'(\d+)%', line)
    if progress_match:
        try:
            return int(progress_match.group(1))
        except (ValueError, IndexError):
            pass

    return None


def parse_log_type(line: str) -> str:
    """
    从日志行解析日志类型

    Args:
        line: 日志行

    Returns:
        日志类型 (info, warning, error, success)
    """
    line_lower = line.lower()

    if any(keyword in line_lower for keyword in ["error", "错误", "failed", "失败", "exception"]):
        return "error"
    elif any(keyword in line_lower for keyword in ["warning", "警告", "warn"]):
        return "warning"
    elif any(keyword in line_lower for keyword in ["success", "成功", "completed", "完成", "done"]):
        return "success"

    return "info"
