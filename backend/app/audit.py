"""
Audit Logging
~~~~~~~~~~~~~
结构化审计日志，记录认证事件、管理操作、数据变更。
"""
import logging
from typing import Any

from app.database import SessionLocal
from app.models import AuditLog

logger = logging.getLogger(__name__)


def log_audit(
    user_id: int | None = None,
    action: str = "",
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """记录审计日志（fire-and-forget，失败时静默）。"""
    try:
        db = SessionLocal()
        try:
            log = AuditLog(
                user_id=user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details_json=details,
                ip_address=ip_address,
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception:
        logger.debug("审计日志写入失败: action=%s", action, exc_info=True)
