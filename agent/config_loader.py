"""Configuration file loader for Agent Skills Framework."""

import os
from pathlib import Path
from typing import Optional, Dict, Any

import yaml

from .config import Config, LLMConfig, BudgetConfig, ExecutionConfig
from .yaml_settings import load_yaml_config, project_root, resolve_path, get_section


class ConfigLoader:
    """Load configuration from YAML (project root config.yaml preferred)."""

    # 兼容旧路径（agent/config.yaml）
    LEGACY_DEFAULT = Path(__file__).parent / "config.yaml"
    LEGACY_LOCAL = Path(__file__).parent / "config.local.yaml"
    ROOT_DEFAULT = project_root() / "config.yaml"
    ROOT_LOCAL = project_root() / "config.local.yaml"

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> Config:
        config = Config()

        # 1) 根目录统一配置（最高优先级）
        data = load_yaml_config(config_path)
        if data:
            config = cls._apply_dict(data, config)
        else:
            # 2) 兼容 agent/ 下旧文件
            if cls.LEGACY_DEFAULT.exists():
                config = cls._load_from_file(cls.LEGACY_DEFAULT, config)
                with open(cls.LEGACY_DEFAULT, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            if cls.LEGACY_LOCAL.exists():
                config = cls._load_from_file(cls.LEGACY_LOCAL, config)
            if config_path:
                path = Path(config_path)
                if path.exists():
                    config = cls._load_from_file(path, config)

        # 3) 仅 YAML 未配置的项，才用环境变量补齐
        config = cls._load_from_env(config, yaml_data=data or {})

        # 4) ollama 可不校验 api_key
        try:
            if config.llm.provider.lower() != "ollama":
                config.validate()
        except ValueError:
            # 允许无 key 时后续组件再失败，避免启动即崩
            pass

        return config

    @classmethod
    def _apply_dict(cls, data: Dict[str, Any], config: Config) -> Config:
        if "llm" in data and isinstance(data["llm"], dict):
            llm_data = data["llm"]
            for key in ("provider", "model", "api_key", "base_url", "temperature", "max_tokens", "timeout"):
                if key in llm_data and llm_data[key] is not None:
                    setattr(config.llm, key, llm_data[key])

        if "budget" in data and isinstance(data["budget"], dict):
            for key in ("total_limit", "warning_threshold", "enable_compression"):
                if key in data["budget"]:
                    setattr(config.budget, key, data["budget"][key])

        if "execution" in data and isinstance(data["execution"], dict):
            for key in (
                "max_skill_retries",
                "enable_streaming",
                "enable_audit_log",
                "enable_metrics",
                "enable_replan",
                "confidence_threshold",
            ):
                if key in data["execution"]:
                    setattr(config.execution, key, data["execution"][key])

        skills_dir = None
        if "skills" in data and isinstance(data["skills"], dict):
            skills_dir = data["skills"].get("dir")
        if "paths" in data and isinstance(data["paths"], dict):
            skills_dir = data["paths"].get("skills_dir") or skills_dir
        if skills_dir:
            config.skills_dir = resolve_path(str(skills_dir))
        else:
            # 默认项目根 skills/
            default_skills = project_root() / "skills"
            if default_skills.exists():
                config.skills_dir = default_skills

        return config

    @classmethod
    def _load_from_file(cls, file_path: Path, config: Config) -> Config:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not data:
                return config
            return cls._apply_dict(data, config)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse config file {file_path}: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load config from {file_path}: {e}")

    @classmethod
    def _load_from_env(cls, config: Config, yaml_data: Optional[Dict[str, Any]] = None) -> Config:
        """仅当 YAML 未配置对应项时，才用环境变量补齐。"""
        yaml_data = yaml_data or {}
        llm_y = yaml_data.get("llm") if isinstance(yaml_data.get("llm"), dict) else {}
        budget_y = yaml_data.get("budget") if isinstance(yaml_data.get("budget"), dict) else {}
        exec_y = yaml_data.get("execution") if isinstance(yaml_data.get("execution"), dict) else {}
        skills_y = yaml_data.get("skills") if isinstance(yaml_data.get("skills"), dict) else {}
        paths_y = yaml_data.get("paths") if isinstance(yaml_data.get("paths"), dict) else {}

        def missing_llm(key: str) -> bool:
            return key not in llm_y or llm_y.get(key) in (None, "")

        if missing_llm("api_key"):
            if api_key := os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"):
                config.llm.api_key = api_key
        if missing_llm("provider") and (provider := os.getenv("LLM_PROVIDER")):
            config.llm.provider = provider
        if missing_llm("model") and (model := os.getenv("LLM_MODEL")):
            config.llm.model = model
        if missing_llm("base_url") and (base_url := os.getenv("LLM_BASE_URL")):
            config.llm.base_url = base_url
        if missing_llm("temperature") and (temperature := os.getenv("LLM_TEMPERATURE")):
            config.llm.temperature = float(temperature)

        if "total_limit" not in budget_y and (limit := os.getenv("TOKEN_LIMIT")):
            config.budget.total_limit = int(limit)
        if "warning_threshold" not in budget_y and (warning := os.getenv("TOKEN_WARNING_THRESHOLD")):
            config.budget.warning_threshold = float(warning)

        if "max_skill_retries" not in exec_y and (retries := os.getenv("MAX_SKILL_RETRIES")):
            config.execution.max_skill_retries = int(retries)
        if "enable_replan" not in exec_y and (enable_replan := os.getenv("ENABLE_REPLAN")):
            config.execution.enable_replan = enable_replan.lower() == "true"

        skills_configured = bool(skills_y.get("dir") or paths_y.get("skills_dir"))
        if not skills_configured and (skills_dir := os.getenv("SKILLS_DIR")):
            config.skills_dir = resolve_path(skills_dir)
        return config

    @classmethod
    def load_profile(cls, profile_name: str) -> Config:
        config = cls.load()
        data = load_yaml_config()
        profiles = data.get("profiles") or {}
        if profile_name not in profiles:
            # 兼容旧 agent 配置
            for path in (cls.LEGACY_LOCAL, cls.LEGACY_DEFAULT):
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        legacy = yaml.safe_load(f) or {}
                    profiles = legacy.get("profiles") or {}
                    if profile_name in profiles:
                        break
        if profile_name not in profiles:
            raise ValueError(f"Profile '{profile_name}' not found in config")
        profile_data = profiles[profile_name]
        return cls._apply_profile(profile_data, config)

    @classmethod
    def _apply_profile(cls, profile_data: Dict[str, Any], config: Config) -> Config:
        def update_config(section, data):
            if isinstance(data, dict):
                for key, value in data.items():
                    if hasattr(section, key):
                        setattr(section, key, value)

        if "llm" in profile_data:
            update_config(config.llm, profile_data["llm"])
        if "budget" in profile_data:
            update_config(config.budget, profile_data["budget"])
        if "execution" in profile_data:
            update_config(config.execution, profile_data["execution"])
        return config
