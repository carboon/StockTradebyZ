"""
Authentication API Router
~~~~~~~~~~~~~~~~~~~~~~~~~~
用户注册、登录、API Key 管理、用量统计、管理员接口
"""
import logging
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    generate_api_key,
    get_api_key_prefix,
    hash_api_key,
    hash_password,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.models import Config
from app.models import ApiKey, UsageLog, User, UserSession
from app.schemas import (
    AdminUserUpdate,
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ChangePasswordRequest,
    DailyVisitFrequency,
    HeartbeatResponse,
    HourlyVisitStats,
    RegisterValidationPromptResponse,
    TokenResponse,
    UsageStatsItem,
    UsageStatsResponse,
    UserListItem,
    UserLogin,
    UserInfo,
    UserRegister,
    VisitFrequencyResponse,
)
from app.audit import log_audit
from app.api.deps import get_admin_user, get_current_active_user, require_user
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

router = APIRouter()


# --- 公开接口 ---


@router.get("/register-validation", response_model=RegisterValidationPromptResponse)
def get_register_validation_prompt(db: Session = Depends(get_db)):
    """获取注册验证问题"""
    register_question = (
        db.query(Config).filter(Config.key == "register_validation_question").first()
    )
    question = (
        register_question.value.strip()
        if register_question and register_question.value
        else settings.register_validation_question.strip()
    )
    return RegisterValidationPromptResponse(question=question)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: UserRegister, request: Request, db: Session = Depends(get_db)):
    """用户注册"""
    register_answer = (
        db.query(Config).filter(Config.key == "register_validation_answer").first()
    )
    expected_answer = (
        register_answer.value.strip()
        if register_answer and register_answer.value
        else settings.register_validation_answer.strip()
    )
    submitted_answer = body.admin_wechat.strip()

    if not expected_answer or submitted_answer != expected_answer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="管理员微信名验证失败",
        )

    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == body.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        display_name=body.display_name,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("用户注册成功: username=%s, user_id=%s", user.username, user.id)
    log_audit(user_id=user.id, action="user_register", target_type="user", target_id=str(user.id), ip_address=request.client.host if request.client else None)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(
        access_token=token,
        user=UserInfo.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: UserLogin, request: Request, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

    # 更新用户登录时间和在线状态
    user.last_login_at = utc_now()
    user.is_online = True

    # 获取客户端IP地址和User Agent
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # 创建用户登录会话记录
    now = utc_now()
    user_session = UserSession(
        user_id=user.id,
        login_at=now,
        last_activity_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(user_session)
    db.commit()

    logger.info("用户登录成功: username=%s, user_id=%s", user.username, user.id)
    log_audit(user_id=user.id, action="user_login", target_type="user", target_id=str(user.id), ip_address=ip_address)

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(
        access_token=token,
        user=UserInfo.model_validate(user),
    )


# --- 需要认证的接口 ---


@router.get("/me", response_model=UserInfo)
def get_me(user: User = Depends(get_current_active_user)):
    """获取当前用户信息"""
    return UserInfo.model_validate(user)


@router.put("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """心跳接口 - 更新用户最后活动时间"""
    now = utc_now()

    # 更新用户在线状态
    user.is_online = True

    # 查找当前活跃的会话（未登出的最近会话）
    active_session = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user.id,
            UserSession.logout_at.is_(None),
        )
        .order_by(UserSession.login_at.desc())
        .first()
    )

    session_id = None
    if active_session:
        active_session.last_activity_at = now
        session_id = active_session.id

    db.commit()

    return HeartbeatResponse(
        is_online=True,
        last_activity_at=now,
        session_id=session_id,
        message="OK",
    )


@router.put("/password")
def change_password(body: ChangePasswordRequest, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """修改密码"""
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码不正确",
        )
    user.hashed_password = hash_password(body.new_password)
    db.commit()
    log_audit(user_id=user.id, action="password_change", target_type="user", target_id=str(user.id))
    logger.info("用户修改密码: user_id=%s", user.id)
    return {"message": "密码修改成功"}


# --- API Key 管理 ---


@router.post("/keys", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(body: ApiKeyCreate, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """创建 API Key"""
    raw_key = generate_api_key()
    api_key = ApiKey(
        user_id=user.id,
        key_hash=hash_api_key(raw_key),
        key_prefix=get_api_key_prefix(raw_key),
        name=body.name,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    logger.info("API Key 创建成功: user_id=%s, key_prefix=%s", user.id, api_key.key_prefix)

    return ApiKeyCreateResponse(
        id=api_key.id,
        key=raw_key,  # 完整 key 仅在创建时返回一次
        key_prefix=api_key.key_prefix,
        name=api_key.name,
    )


@router.get("/keys", response_model=list[ApiKeyResponse])
def list_api_keys(user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """列出当前用户的 API Key"""
    keys = db.query(ApiKey).filter(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc()).all()
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/keys/{key_id}")
def revoke_api_key(key_id: int, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """吊销 API Key"""
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.user_id == user.id).first()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key 不存在")
    api_key.is_active = False
    db.commit()
    logger.info("API Key 已吊销: user_id=%s, key_id=%s", user.id, key_id)
    return {"message": "API Key 已吊销"}


# --- 用量统计 ---


@router.get("/usage", response_model=UsageStatsResponse)
def get_usage(user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """获取近 7 天的用量统计"""
    today = date.today()
    stats = []
    total = 0

    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        rows = (
            db.query(UsageLog.endpoint, func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == user.id,
                func.date(UsageLog.created_at) == d,
            )
            .group_by(UsageLog.endpoint)
            .all()
        )
        endpoints = {row[0]: row[1] for row in rows}
        day_total = sum(endpoints.values())
        total += day_total
        stats.append(UsageStatsItem(date=d.isoformat(), total_calls=day_total, endpoints=endpoints))

    return UsageStatsResponse(stats=stats, total_calls=total)


# --- 管理员接口 ---


@router.get("/admin/users", response_model=list[UserListItem])
def admin_list_users(
    is_online: bool | None = None,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """管理员：列出所有用户

    Args:
        is_online: 可选，按在线状态筛选 (true=仅在线, false=仅离线, None=全部)
    """
    # 计算10天前的日期
    ten_days_ago = utc_now() - timedelta(days=10)

    # 构建基础查询
    query = db.query(User)

    # 如果需要按在线状态筛选
    if is_online is not None:
        query = query.filter(User.is_online == is_online)

    users = query.order_by(User.created_at.desc()).all()

    result = []
    for user in users:
        # 关联查询 UserSession 获取最后登录时间
        last_session = (
            db.query(UserSession.login_at)
            .filter(UserSession.user_id == user.id)
            .order_by(UserSession.login_at.desc())
            .first()
        )
        last_login_at = last_session[0] if last_session else None

        # 计算最近10天访问次数（从 UsageLog 表）
        recent_visit_count = (
            db.query(func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == user.id,
                UsageLog.created_at >= ten_days_ago,
            )
            .scalar()
            or 0
        )

        # 构建 UserListItem 对象
        user_dict = {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
            "daily_quota": user.daily_quota,
            "created_at": user.created_at,
            "last_login_at": last_login_at,
            "is_online": user.is_online,
            "recent_visit_count": recent_visit_count,
        }
        result.append(UserListItem(**user_dict))

    return result


@router.put("/admin/users/{user_id}")
def admin_update_user(user_id: int, body: AdminUserUpdate, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    """管理员：更新用户信息"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if body.is_active is not None:
        user.is_active = body.is_active
    if body.daily_quota is not None:
        user.daily_quota = body.daily_quota
    if body.role is not None:
        if body.role not in ("admin", "user"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的角色")
        user.role = body.role

    db.commit()
    log_audit(user_id=admin.id, action="admin_update_user", target_type="user", target_id=str(user_id), details=body.model_dump(exclude_none=True))
    logger.info("管理员更新用户: admin_id=%s, target_user_id=%s, changes=%s", admin.id, user_id, body.model_dump(exclude_none=True))
    return {"message": "用户信息已更新"}


@router.delete("/admin/users/{user_id}")
def admin_disable_user(user_id: int, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    """管理员：禁用用户并级联删除其观察数据"""
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用自己")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 级联删除用户的观察数据
    from app.models import Watchlist, WatchlistAnalysis

    # 删除观察记录的分析历史
    db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.watchlist_id.in_(
            db.query(Watchlist.id).filter(Watchlist.user_id == user_id)
        )
    ).delete(synchronize_session=False)

    # 删除用户的观察记录
    deleted_count = db.query(Watchlist).filter(Watchlist.user_id == user_id).delete()
    logger.info(f"级联删除用户 {user_id} 的 {deleted_count} 条观察记录")

    # 禁用用户
    user.is_active = False
    db.commit()
    log_audit(user_id=admin.id, action="admin_disable_user", target_type="user", target_id=str(user_id))
    logger.info("管理员禁用用户: admin_id=%s, target_user_id=%s", admin.id, user_id)
    return {"message": "用户已禁用，相关观察数据已清理"}


@router.get("/admin/usage/{target_user_id}", response_model=UsageStatsResponse)
def admin_get_user_usage(target_user_id: int, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    """管理员：查看指定用户用量"""
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    today = date.today()
    stats = []
    total = 0

    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        rows = (
            db.query(UsageLog.endpoint, func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == target_user_id,
                func.date(UsageLog.created_at) == d,
            )
            .group_by(UsageLog.endpoint)
            .all()
        )
        endpoints = {row[0]: row[1] for row in rows}
        day_total = sum(endpoints.values())
        total += day_total
        stats.append(UsageStatsItem(date=d.isoformat(), total_calls=day_total, endpoints=endpoints))

    return UsageStatsResponse(stats=stats, total_calls=total)


# --- 访问频率统计 ---


@router.get("/visit-frequency", response_model=VisitFrequencyResponse)
def get_visit_frequency(user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """获取最近10天的访问频率统计（含每日API调用次数和活跃时段）"""
    today = date.today()
    stats = []
    total_calls = 0
    period_days = 10

    for i in range(period_days - 1, -1, -1):
        d = today - timedelta(days=i)

        # 查询当日总调用次数
        day_total = (
            db.query(func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == user.id,
                func.date(UsageLog.created_at) == d,
            )
            .scalar()
            or 0
        )
        total_calls += day_total

        # 查询当日每小时调用次数（按活跃时段统计）
        hourly_rows = (
            db.query(func.extract("hour", UsageLog.created_at).label("hour"), func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == user.id,
                func.date(UsageLog.created_at) == d,
            )
            .group_by("hour")
            .all()
        )

        hourly_stats = [
            HourlyVisitStats(hour=int(row[0]), count=row[1])
            for row in hourly_rows
        ]

        # 找出峰值时段
        peak_hour = None
        peak_hour_count = 0
        if hourly_stats:
            peak_stat = max(hourly_stats, key=lambda x: x.count)
            peak_hour = peak_stat.hour
            peak_hour_count = peak_stat.count

        stats.append(
            DailyVisitFrequency(
                date=d.isoformat(),
                total_calls=day_total,
                hourly_stats=hourly_stats,
                peak_hour=peak_hour,
                peak_hour_count=peak_hour_count,
            )
        )

    average_calls = round(total_calls / period_days, 2) if period_days > 0 else 0

    return VisitFrequencyResponse(
        stats=stats,
        total_calls=total_calls,
        average_calls_per_day=average_calls,
        period_days=period_days,
    )


@router.get("/admin/visit-frequency/{target_user_id}", response_model=VisitFrequencyResponse)
def admin_get_visit_frequency(
    target_user_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """管理员：查看指定用户的访问频率统计"""
    target = db.query(User).filter(User.id == target_user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    today = date.today()
    stats = []
    total_calls = 0
    period_days = 10

    for i in range(period_days - 1, -1, -1):
        d = today - timedelta(days=i)

        # 查询当日总调用次数
        day_total = (
            db.query(func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == target_user_id,
                func.date(UsageLog.created_at) == d,
            )
            .scalar()
            or 0
        )
        total_calls += day_total

        # 查询当日每小时调用次数（按活跃时段统计）
        hourly_rows = (
            db.query(func.extract("hour", UsageLog.created_at).label("hour"), func.count(UsageLog.id))
            .filter(
                UsageLog.user_id == target_user_id,
                func.date(UsageLog.created_at) == d,
            )
            .group_by("hour")
            .all()
        )

        hourly_stats = [
            HourlyVisitStats(hour=int(row[0]), count=row[1])
            for row in hourly_rows
        ]

        # 找出峰值时段
        peak_hour = None
        peak_hour_count = 0
        if hourly_stats:
            peak_stat = max(hourly_stats, key=lambda x: x.count)
            peak_hour = peak_stat.hour
            peak_hour_count = peak_stat.count

        stats.append(
            DailyVisitFrequency(
                date=d.isoformat(),
                total_calls=day_total,
                hourly_stats=hourly_stats,
                peak_hour=peak_hour,
                peak_hour_count=peak_hour_count,
            )
        )

    average_calls = round(total_calls / period_days, 2) if period_days > 0 else 0

    return VisitFrequencyResponse(
        stats=stats,
        total_calls=total_calls,
        average_calls_per_day=average_calls,
        period_days=period_days,
    )
