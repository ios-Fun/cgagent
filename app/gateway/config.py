"""API 服务配置：config.yaml 默认值 + .env / 环境变量覆盖。"""

from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


def _yaml_defaults() -> dict:
    try:
        from agent.yaml_settings import get_section, resolve_path

        server = get_section("server")
        database = get_section("database")
        redis = get_section("redis")
        skills = get_section("skills")
        llm = get_section("llm")
        rasa = get_section("rasa")
        paths = get_section("paths")

        skills_dir = skills.get("dir") or paths.get("skills_dir") or "skills"
        try:
            skills_dir = str(resolve_path(str(skills_dir)))
        except Exception:
            pass

        enabled = skills.get("enabled")
        if not isinstance(enabled, list):
            enabled = ["unit-healthy", "device-healthy", "tag-trend"]

        return {
            "DEBUG": bool(server.get("debug", True)),
            "HOST": str(server.get("host", "0.0.0.0")),
            "PORT": int(server.get("port", 8000)),
            "CORS_ORIGINS": list(server.get("cors_origins") or [
                "http://localhost:3000",
                "http://localhost:8080",
                "http://127.0.0.1:3000",
            ]),
            "DATABASE_URL": str(database.get("url", "sqlite:///./agent_framework.db")),
            "REDIS_URL": str(redis.get("url", "redis://localhost:6379/0")),
            "SKILLS_DIR": skills_dir,
            "DEFAULT_LLM_PROVIDER": str(llm.get("provider", "ollama")),
            "DEFAULT_LLM_MODEL": str(llm.get("model", "")),
            "DEFAULT_LLM_API_KEY": str(llm.get("api_key") or ""),
            "DEFAULT_LLM_BASE_URL": str(llm.get("base_url") or ""),
            "RASA_URL": str(rasa.get("url", "http://192.168.0.106:5005/webhooks/rest/webhook")),
            "SKILLS": [str(x) for x in enabled],
        }
    except Exception:
        return {}


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    """根目录 config.yaml 设置源（优先级高于环境变量）。"""

    def get_field_value(self, field: FieldInfo, field_name: str) -> Tuple[Any, str, bool]:
        data = _yaml_defaults()
        if field_name in data:
            return data[field_name], field_name, True
        return None, field_name, False

    def __call__(self) -> Dict[str, Any]:
        return _yaml_defaults()


class Settings(BaseSettings):
    """API 服务配置：根目录 YAML 优先，未配置项才用 env / 默认值。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "Agent Framework API"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
    ]

    DATABASE_URL: str = "sqlite:///./agent_framework.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60

    SKILLS_DIR: str = "skills"
    DEFAULT_TENANT_ID: str = "default"

    DEFAULT_LLM_PROVIDER: str = "ollama"
    DEFAULT_LLM_MODEL: str = "glm-4.7"
    DEFAULT_LLM_API_KEY: str = ""
    DEFAULT_LLM_BASE_URL: str = "http://192.168.0.54:11434"

    RASA_URL: str = "http://192.168.0.106:5005/webhooks/rest/webhook"

    SKILLS: List[str] = [
        "unit-healthy",
        "device-healthy",
        "tag-trend",
    ]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # 优先级高 → 低: init > yaml > env > dotenv > secrets
        # 根目录 config.yaml 配了就用它，没配才用环境变量 / 代码默认
        return (
            init_settings,
            YamlConfigSettingsSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
