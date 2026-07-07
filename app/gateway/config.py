"""API 服务配置"""

from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """API 服务配置"""

    # 服务配置
    APP_NAME: str = "Agent Framework API"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS 配置
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
    ]

    # 数据库配置
    DATABASE_URL: str = "sqlite:///./agent_framework.db"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT 配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # 限流配置
    RATE_LIMIT_REQUESTS: int = 100  # 每分钟请求数
    RATE_LIMIT_WINDOW: int = 60  # 时间窗口（秒）

    # Agent 框架配置
    SKILLS_DIR: str = "skills"
    DEFAULT_TENANT_ID: str = "default"

    # LLM 配置
    DEFAULT_LLM_PROVIDER: str = "anthropic"
    DEFAULT_LLM_MODEL: str = "glm-4.7"
    DEFAULT_LLM_API_KEY: str = ""
    DEFAULT_LLM_BASE_URL: str = "https://open.bigmodel.cn/api/anthropic"

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
