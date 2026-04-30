"""
Configuration Management
~~~~~~~~~~~~~~~~~~~~~~~~
应用配置管理，支持环境变量和 .env 文件
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录 (backend 目录的父目录)
PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "StockTrader"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS 配置
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"

    # 数据目录 (绝对路径)
    data_dir: Path = PROJECT_ROOT / "data"
    db_dir: Path = PROJECT_ROOT / "data" / "db"
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    candidates_dir: Path = PROJECT_ROOT / "data" / "candidates"
    review_dir: Path = PROJECT_ROOT / "data" / "review"
    kline_dir: Path = PROJECT_ROOT / "data" / "kline"
    logs_dir: Path = PROJECT_ROOT / "data" / "logs"

    @property
    def database_url(self) -> str:
        """数据库 URL (绝对路径)"""
        self.db_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.db_dir}/stocktrade.db"

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

    # 运行环境
    environment: str = "development"  # development / production


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
