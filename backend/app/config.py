"""
Configuration Management
~~~~~~~~~~~~~~~~~~~~~~~~
应用配置管理，使用环境变量和 .env 文件
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 (backend 目录的父目录)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROOT_ENV_FILE = PROJECT_ROOT / ".env"
BACKEND_ENV_FILE = PROJECT_ROOT / "backend" / ".env"
DEPLOY_ENV_FILE = PROJECT_ROOT / "deploy" / ".env"


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=(str(DEPLOY_ENV_FILE), str(ROOT_ENV_FILE), str(BACKEND_ENV_FILE)),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "StockTrader"
    debug: bool = Field(default=False, alias="DEBUG")
    sql_echo: bool = Field(default=False, alias="SQL_ECHO")
    host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    port: int = Field(default=8000, alias="BACKEND_PORT")

    # CORS 配置
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
        alias="BACKEND_CORS_ORIGINS",
    )

    # 数据目录 (绝对路径)
    data_dir: Path = PROJECT_ROOT / "data"
    db_dir: Path = PROJECT_ROOT / "data" / "db"
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    candidates_dir: Path = PROJECT_ROOT / "data" / "candidates"
    review_dir: Path = PROJECT_ROOT / "data" / "review"
    kline_dir: Path = PROJECT_ROOT / "data" / "kline"
    logs_dir: Path = PROJECT_ROOT / "data" / "logs"

    # 数据库配置
    database_url_env: str = Field(
        default="postgresql://stocktrade:stocktrade123@postgres:5432/stocktrade",
        alias="DATABASE_URL",
    )

    @property
    def database_url(self) -> str:
        """数据库 URL。当前仅支持 PostgreSQL。"""
        return self.database_url_env

    # Tushare 配置
    tushare_token: str = ""

    # LLM API Key (可选)
    zhipuai_api_key: str = ""
    dashscope_api_key: str = ""
    gemini_api_key: str = ""

    # 分析配置
    default_reviewer: str = "quant"  # quant, glm, qwen, gemini
    min_score_threshold: float = 4.0

    # WebSocket 配置
    ws_heartbeat_interval: int = 30

    # 认证配置
    secret_key: str = "change-me-in-production-use-a-random-string"
    access_token_expire_minutes: int = 1440  # 24 hours
    admin_default_username: str = "admin"
    admin_default_password: str = "admin123"

    # Redis 缓存配置
    redis_url: str = Field(default="", alias="REDIS_URL")
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")

    @property
    def redis_url_resolved(self) -> str:
        """解析 Redis URL"""
        if self.redis_url:
            return self.redis_url
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # 运行环境
    environment: str = "development"  # development / production


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
