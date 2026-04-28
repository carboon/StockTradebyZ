"""
WebSocket 工具函数
~~~~~~~~~~~~~~~~~~
提供 WebSocket 日志推送和进度解析功能
"""
import json
import re
from datetime import datetime
from typing import Any, Optional


PROGRESS_JSON_PREFIX = "[PROGRESS_JSON]"


async def send_log(manager, task_id: int, message: str, log_type: str = "info"):
    """
    发送日志到 WebSocket

    Args:
        manager: ConnectionManager 实例
        task_id: 任务 ID
        message: 日志消息
        log_type: 日志类型 (info, warning, error, success)
    """
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
    payload = parse_progress_payload(line)
    if payload and isinstance(payload.get("percent"), int):
        return max(0, min(100, int(payload["percent"])))

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


def parse_progress_payload(line: str) -> Optional[dict[str, Any]]:
    """
    从结构化进度日志解析进度元数据。
    """
    if line.startswith(PROGRESS_JSON_PREFIX):
        raw_payload = line[len(PROGRESS_JSON_PREFIX):].strip()
        if not raw_payload:
            return None
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    # 兼容旧的抓取进度格式: [PROGRESS] fetch 1599/5487
    progress_match = re.match(r"\[PROGRESS\]\s+fetch\s+(\d+)/(\d+)", line)
    if progress_match:
        current = int(progress_match.group(1))
        total = int(progress_match.group(2))
        percent = 0
        if total > 0:
            percent = min(25, 5 + int((current / total) * 20))
        return {
            "kind": "fetch",
            "stage": "fetch_data",
            "current": current,
            "total": total,
            "percent": percent,
            "message": f"抓取原始数据 {current}/{total}",
        }

    return None


def is_progress_line(line: str) -> bool:
    return line.startswith(PROGRESS_JSON_PREFIX) or line.startswith("[PROGRESS]")


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
