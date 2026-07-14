"""长期记忆配置：根目录 config.yaml 的 memory 段优先，未配才用环境变量 / 默认值。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class MemoryConfig(BaseModel):
    """全局记忆机制配置。"""

    enabled: bool = Field(default=True)
    debounce_seconds: int = Field(default=5, ge=1, le=300)
    max_facts: int = Field(default=100, ge=10, le=500)
    fact_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    injection_enabled: bool = Field(default=True)
    max_injection_tokens: int = Field(default=2000, ge=100, le=8000)
    guaranteed_categories: List[str] = Field(default_factory=lambda: ["correction"])
    guaranteed_token_budget: int = Field(default=500, ge=50, le=2000)
    llm_model: str = Field(
        default="Jarcgon/Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-uncenfull"
    )
    llm_base_url: str = Field(default="http://192.168.0.54:11434")
    llm_temperature: float = Field(default=0.2)
    use_llm_update: bool = Field(default=True)
    use_rule_fallback: bool = Field(default=True)


class MemorySettings(BaseSettings):
    """环境变量补齐层（仅 YAML 未配置时使用）。"""

    MEMORY_ENABLED: Optional[bool] = None
    MEMORY_DEBOUNCE_SECONDS: Optional[int] = None
    MEMORY_MAX_FACTS: Optional[int] = None
    MEMORY_FACT_CONFIDENCE_THRESHOLD: Optional[float] = None
    MEMORY_INJECTION_ENABLED: Optional[bool] = None
    MEMORY_MAX_INJECTION_TOKENS: Optional[int] = None
    MEMORY_USE_LLM_UPDATE: Optional[bool] = None
    MEMORY_LLM_MODEL: Optional[str] = None
    MEMORY_LLM_BASE_URL: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


_memory_config: Optional[MemoryConfig] = None


def _from_yaml() -> dict:
    try:
        from agent.yaml_settings import get_section

        return get_section("memory")
    except Exception:
        return {}


def get_memory_config() -> MemoryConfig:
    global _memory_config
    if _memory_config is not None:
        return _memory_config

    y = _from_yaml()
    y_llm = y.get("llm") if isinstance(y.get("llm"), dict) else {}

    try:
        from agent.yaml_settings import get_section

        synth = get_section("synthesis_llm")
        root_llm = get_section("llm")
    except Exception:
        synth, root_llm = {}, {}

    # 1) YAML 优先
    model = y_llm.get("model") or synth.get("model") or root_llm.get("model")
    base_url = y_llm.get("base_url") or synth.get("base_url") or root_llm.get("base_url")
    temperature = y_llm.get("temperature")

    cfg = MemoryConfig(
        enabled=bool(y["enabled"]) if "enabled" in y else True,
        debounce_seconds=int(y["debounce_seconds"]) if "debounce_seconds" in y else 5,
        max_facts=int(y["max_facts"]) if "max_facts" in y else 100,
        fact_confidence_threshold=(
            float(y["fact_confidence_threshold"]) if "fact_confidence_threshold" in y else 0.7
        ),
        injection_enabled=bool(y["injection_enabled"]) if "injection_enabled" in y else True,
        max_injection_tokens=int(y["max_injection_tokens"]) if "max_injection_tokens" in y else 2000,
        guaranteed_categories=list(y["guaranteed_categories"]) if "guaranteed_categories" in y else ["correction"],
        guaranteed_token_budget=int(y["guaranteed_token_budget"]) if "guaranteed_token_budget" in y else 500,
        llm_model=str(model) if model else "Jarcgon/Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-uncenfull",
        llm_base_url=str(base_url) if base_url else "http://192.168.0.54:11434",
        llm_temperature=float(temperature) if temperature is not None else 0.2,
        use_llm_update=bool(y["use_llm_update"]) if "use_llm_update" in y else True,
        use_rule_fallback=bool(y["use_rule_fallback"]) if "use_rule_fallback" in y else True,
    )

    # 2) YAML 未配置的项，才用环境变量补齐
    env = MemorySettings()
    if "enabled" not in y and env.MEMORY_ENABLED is not None:
        cfg.enabled = env.MEMORY_ENABLED
    if "debounce_seconds" not in y and env.MEMORY_DEBOUNCE_SECONDS is not None:
        cfg.debounce_seconds = env.MEMORY_DEBOUNCE_SECONDS
    if "max_facts" not in y and env.MEMORY_MAX_FACTS is not None:
        cfg.max_facts = env.MEMORY_MAX_FACTS
    if "fact_confidence_threshold" not in y and env.MEMORY_FACT_CONFIDENCE_THRESHOLD is not None:
        cfg.fact_confidence_threshold = env.MEMORY_FACT_CONFIDENCE_THRESHOLD
    if "injection_enabled" not in y and env.MEMORY_INJECTION_ENABLED is not None:
        cfg.injection_enabled = env.MEMORY_INJECTION_ENABLED
    if "max_injection_tokens" not in y and env.MEMORY_MAX_INJECTION_TOKENS is not None:
        cfg.max_injection_tokens = env.MEMORY_MAX_INJECTION_TOKENS
    if "use_llm_update" not in y and env.MEMORY_USE_LLM_UPDATE is not None:
        cfg.use_llm_update = env.MEMORY_USE_LLM_UPDATE
    if "model" not in y_llm and not model and env.MEMORY_LLM_MODEL is not None:
        cfg.llm_model = env.MEMORY_LLM_MODEL
    if "base_url" not in y_llm and not base_url and env.MEMORY_LLM_BASE_URL is not None:
        cfg.llm_base_url = env.MEMORY_LLM_BASE_URL

    _memory_config = cfg
    return _memory_config


def set_memory_config(config: MemoryConfig) -> None:
    global _memory_config
    _memory_config = config


def reload_memory_config() -> MemoryConfig:
    global _memory_config
    _memory_config = None
    return get_memory_config()
