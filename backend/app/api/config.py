"""
Config API
~~~~~~~~~~
配置管理相关 API
"""
import asyncio
import os
import time
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.database import get_db
from app.models import Config
from app.schemas import (
    ConfigItem,
    ConfigUpdate,
    ConfigResponse,
    TushareVerifyRequest,
    TushareVerifyResponse,
)
from app.config import DEPLOY_ENV_FILE, PROJECT_ROOT, settings, get_settings
from app.services.auto_update_service import (
    AUTO_DAILY_UPDATE_ENABLED_KEY,
    AUTO_DAILY_UPDATE_TIME_KEY,
    get_config_default_value,
    normalize_auto_update_config_value,
)
from app.services.tushare_service import TushareService

router = APIRouter()

ENV_KEY_MAP = {
    "tushare_token": "TUSHARE_TOKEN",
    "zhipuai_api_key": "ZHIPUAI_API_KEY",
    "dashscope_api_key": "DASHSCOPE_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "bocha_api_key": "BOCHA_API_KEY",
    "tavily_api_key": "TAVILY_API_KEY",
    "default_reviewer": "DEFAULT_REVIEWER",
    "min_score_threshold": "MIN_SCORE_THRESHOLD",
    "register_validation_question": "REGISTER_VALIDATION_QUESTION",
    "register_validation_answer": "REGISTER_VALIDATION_ANSWER",
    "backend_host": "BACKEND_HOST",
    "backend_port": "BACKEND_PORT",
    "backend_cors_origins": "BACKEND_CORS_ORIGINS",
    "vite_api_base_url": "VITE_API_BASE_URL",
}

CONFIG_DEFAULT_KEYS = [
    "tushare_token",
    "zhipuai_api_key",
    "dashscope_api_key",
    "gemini_api_key",
    "deepseek_api_key",
    "bocha_api_key",
    "tavily_api_key",
    "default_reviewer",
    "min_score_threshold",
    "register_validation_question",
    "register_validation_answer",
    AUTO_DAILY_UPDATE_ENABLED_KEY,
    AUTO_DAILY_UPDATE_TIME_KEY,
]


def _to_env_key(key: str) -> str:
    return ENV_KEY_MAP.get(key.lower(), key.upper())


def _resolve_runtime_config_value(db: Session, key: str) -> str:
    env_value = os.environ.get(key.upper(), "")
    if env_value and env_value != "your_tushare_token_here":
        return env_value

    db_config = db.query(Config).filter(Config.key == key).first()
    if db_config:
        return db_config.value
    return get_config_default_value(key)


@router.get("/", response_model=ConfigResponse)
def get_configs(db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> ConfigResponse:
    """获取所有配置"""
    # 同时从数据库和环境变量读取
    configs = {}
    env_keys = CONFIG_DEFAULT_KEYS

    # 从环境变量读取
    for key in env_keys:
        configs[key] = _resolve_runtime_config_value(db, key)

    # 从数据库读取额外配置
    db_configs = db.query(Config).all()
    for c in db_configs:
        configs[c.key] = c.value

    # 转换为响应格式
    config_items = [
        ConfigItem(key=k, value=v, description="")
        for k, v in configs.items()
    ]

    return ConfigResponse(configs=config_items)


@router.put("/", response_model=ConfigItem)
def update_config(config: ConfigUpdate, db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> ConfigItem:
    """更新配置"""
    config_key = str(config.key).strip()
    config_value = str(config.value)
    normalized_value = normalize_auto_update_config_value(config_key, config_value)

    db_config = db.query(Config).filter(Config.key == config_key).first()
    if db_config:
        db_config.value = normalized_value
    else:
        db_config = Config(key=config_key, value=normalized_value)
        db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return ConfigItem(key=db_config.key, value=db_config.value, description=db_config.description)


@router.post("/verify-tushare", response_model=TushareVerifyResponse)
async def verify_tushare(request: TushareVerifyRequest, admin=Depends(get_admin_user)) -> TushareVerifyResponse:
    """验证 Tushare Token"""
    try:
        service = TushareService(token=request.token)
        valid, message = await asyncio.to_thread(service.verify_token)
        return TushareVerifyResponse(valid=valid, message=message)
    except Exception as e:
        return TushareVerifyResponse(valid=False, message=f"验证失败: {str(e)}")


@router.post("/save-env")
def save_env(config: dict, db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> dict:
    """保存环境变量到 .env 文件"""
    env_file = DEPLOY_ENV_FILE
    env_file.parent.mkdir(parents=True, exist_ok=True)

    # 读取现有内容
    existing_lines = []
    if env_file.exists():
        with open(env_file, "r") as f:
            existing_lines = f.readlines()

    # 更新配置
    normalized_config = {
        _to_env_key(str(key)): str(value)
        for key, value in config.items()
    }
    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=")[0].strip()
            env_key = _to_env_key(key)
            if env_key in normalized_config:
                new_lines.append(f"{env_key}={normalized_config[env_key]}\n")
                updated_keys.add(env_key)
            else:
                new_lines.append(line)

    # 添加新配置
    for env_key, value in normalized_config.items():
        if env_key not in updated_keys:
            new_lines.append(f"{env_key}={value}\n")

    # 写入文件
    with open(env_file, "w") as f:
        f.writelines(new_lines)

    for env_key, value in normalized_config.items():
        os.environ[env_key] = value

    # 同步保存到数据库，便于页面回显和兜底读取
    for raw_key, raw_value in config.items():
        db_key = str(raw_key).lower()
        db_value = str(raw_value)
        db_config = db.query(Config).filter(Config.key == db_key).first()
        if db_config:
            db_config.value = db_value
        else:
            db.add(Config(key=db_key, value=db_value))
    db.commit()

    get_settings.cache_clear()

    return {"status": "ok", "message": "环境变量已保存"}


@router.get("/reload")
def reload_config(admin=Depends(get_admin_user)) -> dict:
    """重新加载配置"""
    get_settings.cache_clear()
    return {"status": "ok", "message": "配置已重新加载"}


@router.get("/tushare-status")
async def get_tushare_status(db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> dict:
    """获取 Tushare 配置状态"""
    token = _resolve_runtime_config_value(db, "tushare_token")

    if not token:
        return {
            "configured": False,
            "available": False,
            "message": "TUSHARE_TOKEN 未配置，请先在配置页完成设置。",
        }

    try:
        from app.services.tushare_service import TushareService as RuntimeTushareService

        service = RuntimeTushareService(token=token)
        valid = True
        verify_message = "Token 已配置"

        verify_cache = getattr(RuntimeTushareService, "_verify_cache", {})
        cached_verify = verify_cache.get(token) if isinstance(verify_cache, dict) else None
        if cached_verify and time.time() - cached_verify[0] < 300:
            valid, verify_message = cached_verify[1]
        else:
            verify_message = "Token 已配置（未实时验证）"

        data_status = (
            await asyncio.to_thread(service.check_data_status, include_remote_checks=False)
            if valid
            else None
        )
        return {
            "configured": True,
            "available": valid,
            "message": verify_message,
            "token_prefix": token[:8] + "..." if len(token) > 8 else "***",
            "data_status": data_status,
        }
    except Exception as e:
        return {
            "configured": True,
            "available": False,
            "message": f"Tushare 检查失败: {str(e)}",
            "error": str(e),
        }
