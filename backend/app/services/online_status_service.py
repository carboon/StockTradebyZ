"""
Online Status Management Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
用户在线状态管理后台服务
- 定时检查超过30分钟无活动的用户
- 自动设置离线状态并更新会话登出时间
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import User, UserSession
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

# 在线超时时间（分钟）
ONLINE_TIMEOUT_MINUTES = 30
# 检查间隔（秒）
CHECK_INTERVAL_SECONDS = 300  # 5分钟


class OnlineStatusService:
    """用户在线状态管理服务"""

    def __init__(self, check_interval: int = CHECK_INTERVAL_SECONDS):
        self.check_interval = check_interval
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False

    def start(self) -> None:
        """启动后台任务"""
        if self._running:
            return
        self._running = True
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="online-status-service")
        logger.info("在线状态管理服务已启动")

    async def stop(self) -> None:
        """停止后台任务"""
        if not self._running:
            return
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("在线状态管理服务已停止")

    async def _run_loop(self) -> None:
        """主循环"""
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("在线状态检查失败: %s", exc)

            # 等待下次检查
            if self._stop_event is not None:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.check_interval,
                    )
                    return
                except asyncio.TimeoutError:
                    continue

    async def run_once(self) -> dict[str, int]:
        """执行一次在线状态检查

        Returns:
            包含统计信息的字典
        """
        return await asyncio.to_thread(self._check_offline_users)

    def _check_offline_users(self) -> dict[str, int]:
        """检查并更新离线用户

        Returns:
            包含统计信息的字典
        """
        db: Session | None = None
        try:
            db = SessionLocal()
            now = utc_now()
            timeout_threshold = now - timedelta(minutes=ONLINE_TIMEOUT_MINUTES)

            # 查找超过30分钟无活动的在线用户
            offline_users = (
                db.query(User)
                .filter(User.is_online.is_(True))
                .filter(
                    (User.last_login_at < timeout_threshold) |
                    (User.last_login_at.is_(None))
                )
                .all()
            )

            updated_count = 0
            session_updated_count = 0

            for user in offline_users:
                # 检查该用户的活跃会话
                active_sessions = (
                    db.query(UserSession)
                    .filter(
                        UserSession.user_id == user.id,
                        UserSession.logout_at.is_(None),
                        UserSession.last_activity_at < timeout_threshold,
                    )
                    .all()
                )

                if active_sessions:
                    # 有超时的活跃会话，设置离线
                    user.is_online = False
                    updated_count += 1

                    # 更新会话登出时间
                    for session in active_sessions:
                        session.logout_at = now
                        session_updated_count += 1

            if updated_count > 0:
                db.commit()
                logger.info(
                    "在线状态检查完成: %d 个用户设置为离线, %d 个会话已更新",
                    updated_count,
                    session_updated_count,
                )

            return {
                "offline_users_set": updated_count,
                "sessions_updated": session_updated_count,
            }

        except Exception as exc:
            if db is not None:
                db.rollback()
            logger.exception("检查离线用户时出错: %s", exc)
            raise
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def get_active_user_count(db: Session) -> int:
        """获取当前在线用户数"""
        return (
            db.query(User)
            .filter(User.is_online.is_(True))
            .count()
        )

    @staticmethod
    def get_user_online_status(user_id: int, db: Session) -> dict[str, any]:
        """获取指定用户的在线状态详情"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"is_online": False, "error": "User not found"}

        # 获取最近的活跃会话
        active_session = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user_id,
                UserSession.logout_at.is_(None),
            )
            .order_by(UserSession.last_activity_at.desc())
            .first()
        )

        return {
            "is_online": user.is_online,
            "last_login_at": user.last_login_at,
            "active_session_id": active_session.id if active_session else None,
            "last_activity_at": active_session.last_activity_at if active_session else None,
        }


# 全局服务实例
_online_status_service: OnlineStatusService | None = None


def get_online_status_service() -> OnlineStatusService:
    """获取在线状态管理服务单例"""
    global _online_status_service
    if _online_status_service is None:
        _online_status_service = OnlineStatusService()
    return _online_status_service
