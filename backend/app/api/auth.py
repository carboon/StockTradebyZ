"""
Authentication API Router
~~~~~~~~~~~~~~~~~~~~~~~~~~
用户注册、登录、API Key 管理、用量统计、管理员接口
"""
import csv
import io
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
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
from app.models import ApiKey, Config, Stock, UsageLog, User, UserSession, Watchlist
from app.schemas import (
    AdminUserUpdate,
    CsvImportResult,
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
from app.api.deps import get_admin_user, get_current_active_user
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

router = APIRouter()

RECOVERABLE_LOGIN_USERS: dict[str, int] = {
    "307god": 3,
    "chenyujun": 5,
    "hntest": 7,
    "江橙澄": 14,
    "DotakuHX": 16,
    "暴走的美芽": 18,
    "suppermoon": 20,
    "pangzipang38": 21,
    "youmo110": 23,
    "悠悠果": 26,
    "Yajun": 27,
    "yidu": 28,
}

_USER_EXPORT_HEADERS = [
    "id",
    "username",
    "display_name",
    "role",
    "is_active",
    "daily_quota",
    "last_login_at",
    "is_online",
    "created_at",
    "updated_at",
]

_USER_IMPORT_REQUIRED_HEADERS = {
    "username",
    "role",
    "is_active",
    "daily_quota",
}

_USER_IMPORT_OPTIONAL_HEADERS = {
    "id",
    "display_name",
    "last_login_at",
    "is_online",
    "created_at",
    "updated_at",
    "password",
}

_WATCHLIST_EXPORT_HEADERS = [
    "id",
    "user_id",
    "username",
    "code",
    "add_reason",
    "entry_price",
    "entry_date",
    "position_ratio",
    "priority",
    "is_active",
    "added_at",
]

_WATCHLIST_IMPORT_REQUIRED_HEADERS = {
    "username",
    "code",
    "is_active",
    "priority",
}

_WATCHLIST_IMPORT_OPTIONAL_HEADERS = {
    "id",
    "user_id",
    "add_reason",
    "entry_price",
    "entry_date",
    "position_ratio",
    "added_at",
}


def _build_csv_response(filename: str, headers: list[str], rows: list[list[object | None]]) -> Response:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])

    content = "\ufeff" + buffer.getvalue()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _load_csv_upload(upload: UploadFile) -> tuple[list[str], list[dict[str, str]]]:
    raw = upload.file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    decoded: str | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV 文件编码不支持，请使用 UTF-8 或 GB18030")

    reader = csv.DictReader(io.StringIO(decoded))
    if reader.fieldnames is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV 文件缺少表头")

    rows: list[dict[str, str]] = []
    for row in reader:
        normalized_row: dict[str, str] = {}
        for key, value in row.items():
            if key is None:
                continue
            normalized_row[key.strip()] = "" if value is None else str(value)
        rows.append(normalized_row)
    return [header.strip() for header in reader.fieldnames], rows


def _normalize_csv_field(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_bool(value: object | None, field_name: str, row_no: int, *, required: bool = False) -> bool | None:
    text = _normalize_csv_field(value)
    if not text:
        if required:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不能为空")
        return None

    normalized = text.lower()
    if normalized in {"1", "true", "yes", "y", "t", "是", "启用"}:
        return True
    if normalized in {"0", "false", "no", "n", "f", "否", "禁用"}:
        return False
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不是有效布尔值")


def _parse_int(value: object | None, field_name: str, row_no: int, *, required: bool = False, minimum: int | None = None) -> int | None:
    text = _normalize_csv_field(value)
    if not text:
        if required:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不能为空")
        return None
    try:
        parsed = int(text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不是有效整数") from exc
    if minimum is not None and parsed < minimum:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不能小于 {minimum}")
    return parsed


def _parse_float(value: object | None, field_name: str, row_no: int, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    text = _normalize_csv_field(value)
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不是有效数字") from exc
    if minimum is not None and parsed < minimum:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不能小于 {minimum}")
    if maximum is not None and parsed > maximum:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不能大于 {maximum}")
    return parsed


def _parse_date(value: object | None, field_name: str, row_no: int) -> date | None:
    text = _normalize_csv_field(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不是有效日期") from exc


def _parse_datetime(value: object | None, field_name: str, row_no: int) -> datetime | None:
    text = _normalize_csv_field(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {row_no} 行字段 {field_name} 不是有效日期时间") from exc


def _validate_headers(fieldnames: list[str] | None, required: set[str], optional: set[str], *, sheet_name: str) -> None:
    if not fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{sheet_name} CSV 文件缺少表头")

    normalized_headers = [header.strip() for header in fieldnames if header is not None]
    missing = [header for header in required if header not in normalized_headers]
    if missing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{sheet_name} CSV 缺少必要字段: {', '.join(missing)}")

    allowed_headers = required | optional
    unknown = [header for header in normalized_headers if header and header not in allowed_headers]
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{sheet_name} CSV 含有不支持的字段: {', '.join(unknown)}")


def _build_user_export_rows(db: Session) -> list[list[object | None]]:
    rows: list[list[object | None]] = []
    users = db.query(User).order_by(User.id.asc()).all()
    for user in users:
        rows.append([
            user.id,
            user.username,
            user.display_name,
            user.role,
            user.is_active,
            user.daily_quota,
            user.last_login_at.isoformat() if user.last_login_at else None,
            user.is_online,
            user.created_at.isoformat() if user.created_at else None,
            user.updated_at.isoformat() if user.updated_at else None,
        ])
    return rows


def _build_watchlist_export_rows(db: Session) -> list[list[object | None]]:
    rows: list[list[object | None]] = []
    query = (
        db.query(Watchlist, User.username)
        .join(User, User.id == Watchlist.user_id)
        .order_by(Watchlist.user_id.asc(), Watchlist.code.asc())
    )
    for watchlist, username in query.all():
        rows.append([
            watchlist.id,
            watchlist.user_id,
            username,
            watchlist.code,
            watchlist.add_reason,
            watchlist.entry_price,
            watchlist.entry_date.isoformat() if watchlist.entry_date else None,
            watchlist.position_ratio,
            watchlist.priority,
            watchlist.is_active,
            watchlist.added_at.isoformat() if watchlist.added_at else None,
        ])
    return rows


def _build_user_row_lookup(db: Session) -> dict[str, User]:
    return {
        user.username: user
        for user in db.query(User).all()
    }


def _build_stock_lookup(db: Session) -> dict[str, Stock]:
    return {
        stock.code: stock
        for stock in db.query(Stock).all()
    }


def _import_users_from_csv(upload: UploadFile, db: Session) -> CsvImportResult:
    fieldnames, rows = _load_csv_upload(upload)
    _validate_headers(fieldnames, _USER_IMPORT_REQUIRED_HEADERS, _USER_IMPORT_OPTIONAL_HEADERS, sheet_name="用户")

    existing_users = _build_user_row_lookup(db)
    seen_usernames: set[str] = set()
    result = CsvImportResult(total_rows=len(rows))

    for idx, row in enumerate(rows, start=2):
        username = _normalize_csv_field(row.get("username"))
        if not username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行字段 username 不能为空")
        if username in seen_usernames:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行用户名重复: {username}")
        seen_usernames.add(username)

        role = _normalize_csv_field(row.get("role"))
        if role not in {"admin", "user"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行字段 role 只能是 admin 或 user")

        is_active = _parse_bool(row.get("is_active"), "is_active", idx, required=True)
        daily_quota = _parse_int(row.get("daily_quota"), "daily_quota", idx, required=True, minimum=0)
        if daily_quota is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行字段 daily_quota 不能为空")

        display_name = _normalize_csv_field(row.get("display_name")) or None
        is_online = _parse_bool(row.get("is_online"), "is_online", idx)
        last_login_at = _parse_datetime(row.get("last_login_at"), "last_login_at", idx)
        created_at = _parse_datetime(row.get("created_at"), "created_at", idx)
        updated_at = _parse_datetime(row.get("updated_at"), "updated_at", idx)
        password = _normalize_csv_field(row.get("password"))

        user = existing_users.get(username)
        if user is None:
            if not password:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行新增用户缺少 password")
            if len(password) < 6:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行字段 password 长度不能少于 6 位")
            user = User(
                username=username,
                hashed_password=hash_password(password),
                display_name=display_name,
                role=role,
                is_active=is_active,
                daily_quota=daily_quota,
                last_login_at=last_login_at,
                is_online=is_online if is_online is not None else False,
            )
            if created_at is not None:
                user.created_at = created_at
            if updated_at is not None:
                user.updated_at = updated_at
            db.add(user)
            existing_users[username] = user
            result.inserted_count += 1
            continue

        user.display_name = display_name
        user.role = role
        user.is_active = is_active
        user.daily_quota = daily_quota
        user.last_login_at = last_login_at
        if is_online is not None:
            user.is_online = is_online
        user.updated_at = updated_at or utc_now()
        result.updated_count += 1

    return result


def _import_watchlist_from_csv(upload: UploadFile, db: Session) -> CsvImportResult:
    fieldnames, rows = _load_csv_upload(upload)
    _validate_headers(fieldnames, _WATCHLIST_IMPORT_REQUIRED_HEADERS, _WATCHLIST_IMPORT_OPTIONAL_HEADERS, sheet_name="重点观察")

    users_by_username = _build_user_row_lookup(db)
    stocks_by_code = _build_stock_lookup(db)
    existing_watchlist = {
        (item.user_id, item.code): item
        for item in db.query(Watchlist).all()
    }
    seen_keys: set[tuple[int, str]] = set()
    result = CsvImportResult(total_rows=len(rows))

    for idx, row in enumerate(rows, start=2):
        username = _normalize_csv_field(row.get("username"))
        if not username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行字段 username 不能为空")

        user = users_by_username.get(username)
        if user is None:
            user_id_text = _normalize_csv_field(row.get("user_id"))
            if user_id_text and user_id_text.isdigit():
                user = db.query(User).filter(User.id == int(user_id_text)).first()
        if user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行用户不存在: {username}")

        code = _normalize_csv_field(row.get("code")).upper()
        if not code or len(code) != 6 or not code.isdigit():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行字段 code 不是有效的 6 位股票代码")
        if code not in stocks_by_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行股票不存在: {code}")

        key = (user.id, code)
        if key in seen_keys:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行观察项重复: {username}/{code}")
        seen_keys.add(key)

        add_reason = _normalize_csv_field(row.get("add_reason")) or None
        entry_price = _parse_float(row.get("entry_price"), "entry_price", idx, minimum=0)
        entry_date = _parse_date(row.get("entry_date"), "entry_date", idx)
        position_ratio = _parse_float(row.get("position_ratio"), "position_ratio", idx, minimum=0, maximum=1)
        priority = _parse_int(row.get("priority"), "priority", idx, required=True, minimum=0)
        if priority is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"第 {idx} 行字段 priority 不能为空")
        is_active = _parse_bool(row.get("is_active"), "is_active", idx, required=True)
        added_at = _parse_datetime(row.get("added_at"), "added_at", idx)

        watchlist = existing_watchlist.get(key)
        if watchlist is None:
            watchlist = Watchlist(
                user_id=user.id,
                code=code,
                add_reason=add_reason,
                entry_price=entry_price,
                entry_date=entry_date,
                position_ratio=position_ratio,
                priority=priority,
                is_active=is_active if is_active is not None else True,
            )
            if added_at is not None:
                watchlist.added_at = added_at
            db.add(watchlist)
            existing_watchlist[key] = watchlist
            result.inserted_count += 1
            continue

        watchlist.add_reason = add_reason
        watchlist.entry_price = entry_price
        watchlist.entry_date = entry_date
        watchlist.position_ratio = position_ratio
        watchlist.priority = priority
        watchlist.is_active = is_active if is_active is not None else watchlist.is_active
        if added_at is not None:
            watchlist.added_at = added_at
        result.updated_count += 1

    return result


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


def _initialize_recovered_user(username: str, password: str, db: Session) -> User | None:
    recovered_user_id = RECOVERABLE_LOGIN_USERS.get(username)
    if recovered_user_id is None:
        return None

    user = User(
        id=recovered_user_id,
        username=username,
        hashed_password=hash_password(password),
        role="user",
        is_active=True,
        daily_quota=1000,
    )
    db.add(user)
    db.flush()
    logger.info("恢复用户首次登录初始化: username=%s, user_id=%s", user.username, user.id)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: UserLogin, request: Request, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == body.username).first()
    if user is None:
        user = _initialize_recovered_user(body.username, body.password, db)
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


@router.get("/admin/users/export")
def admin_export_users(_admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    """管理员：导出所有用户信息为 CSV"""
    filename = f"users_export_{utc_now().strftime('%Y%m%d_%H%M%S')}.csv"
    return _build_csv_response(filename, _USER_EXPORT_HEADERS, _build_user_export_rows(db))


@router.post("/admin/users/import", response_model=CsvImportResult)
def admin_import_users(
    upload_file: UploadFile = File(..., description="CSV 文件"),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """管理员：导入用户信息（CSV）"""
    if upload_file.filename and not upload_file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请上传 CSV 文件")

    try:
        result = _import_users_from_csv(upload_file, db)
        db.commit()
        log_audit(
            user_id=admin.id,
            action="admin_import_users",
            target_type="user",
            target_id="bulk",
            details=result.model_dump(),
        )
        logger.info(
            "管理员导入用户 CSV: admin_id=%s, total=%s, inserted=%s, updated=%s",
            admin.id,
            result.total_rows,
            result.inserted_count,
            result.updated_count,
        )
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("管理员导入用户 CSV 失败: admin_id=%s", admin.id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"用户 CSV 导入失败: {exc}") from exc


@router.get("/admin/watchlist/export")
def admin_export_watchlist(_admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    """管理员：导出所有用户的重点观察信息为 CSV"""
    filename = f"watchlist_export_{utc_now().strftime('%Y%m%d_%H%M%S')}.csv"
    return _build_csv_response(filename, _WATCHLIST_EXPORT_HEADERS, _build_watchlist_export_rows(db))


@router.post("/admin/watchlist/import", response_model=CsvImportResult)
def admin_import_watchlist(
    upload_file: UploadFile = File(..., description="CSV 文件"),
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    """管理员：导入所有用户的重点观察信息（CSV）"""
    if upload_file.filename and not upload_file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请上传 CSV 文件")

    try:
        result = _import_watchlist_from_csv(upload_file, db)
        db.commit()
        log_audit(
            user_id=admin.id,
            action="admin_import_watchlist",
            target_type="watchlist",
            target_id="bulk",
            details=result.model_dump(),
        )
        logger.info(
            "管理员导入重点观察 CSV: admin_id=%s, total=%s, inserted=%s, updated=%s",
            admin.id,
            result.total_rows,
            result.inserted_count,
            result.updated_count,
        )
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("管理员导入重点观察 CSV 失败: admin_id=%s", admin.id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"重点观察 CSV 导入失败: {exc}") from exc


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
