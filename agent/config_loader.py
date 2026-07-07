"""Configuration file loader for Agent Skills Framework."""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

from .config import Config, LLMConfig, BudgetConfig, ExecutionConfig


class ConfigLoader:
    """Load configuration from YAML file."""

    # 默认配置文件路径
    DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"
    LOCAL_CONFIG_PATH = Path(__file__).parent / "config.local.yaml"

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> Config:
        """Load configuration from file.

        Args:
            config_path: Optional path to config file

        Returns:
            Config object
        """
        config = Config()

        # 1. 加载默认配置文件
        if cls.DEFAULT_CONFIG_PATH.exists():
            config = cls._load_from_file(cls.DEFAULT_CONFIG_PATH, config)

        # 2. 加载本地配置文件（覆盖默认配置）
        if cls.LOCAL_CONFIG_PATH.exists():
            config = cls._load_from_file(cls.LOCAL_CONFIG_PATH, config)

        # 3. 加载用户指定的配置文件
        if config_path:
            path = Path(config_path)
            if path.exists():
                config = cls._load_from_file(path, config)
            else:
                raise FileNotFoundError(f"Config file not found: {config_path}")

        # 4. 从环境变量加载（覆盖文件配置）
        config = cls._load_from_env(config)

        # 5. 验证配置
        config.validate()

        return config

    @classmethod
    def _load_from_file(cls, file_path: Path, config: Config) -> Config:
        """Load configuration from YAML file.

        Args:
            file_path: Path to YAML file
            config: Existing config to update

        Returns:
            Updated config
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                return config

            # 更新 LLM 配置
            if "llm" in data:
                llm_data = data["llm"]
                if "provider" in llm_data:
                    config.llm.provider = llm_data["provider"]
                if "model" in llm_data:
                    config.llm.model = llm_data["model"]
                if "api_key" in llm_data:
                    config.llm.api_key = llm_data["api_key"]
                if "base_url" in llm_data:
                    config.llm.base_url = llm_data["base_url"]
                if "temperature" in llm_data:
                    config.llm.temperature = llm_data["temperature"]
                if "max_tokens" in llm_data:
                    config.llm.max_tokens = llm_data["max_tokens"]
                if "timeout" in llm_data:
                    config.llm.timeout = llm_data["timeout"]

            # 更新 Token 预算配置
            if "budget" in data:
                budget_data = data["budget"]
                if "total_limit" in budget_data:
                    config.budget.total_limit = budget_data["total_limit"]
                if "warning_threshold" in budget_data:
                    config.budget.warning_threshold = budget_data["warning_threshold"]
                if "enable_compression" in budget_data:
                    config.budget.enable_compression = budget_data["enable_compression"]

            # 更新执行配置
            if "execution" in data:
                exec_data = data["execution"]
                if "max_skill_retries" in exec_data:
                    config.execution.max_skill_retries = exec_data["max_skill_retries"]
                if "enable_streaming" in exec_data:
                    config.execution.enable_streaming = exec_data["enable_streaming"]
                if "enable_audit_log" in exec_data:
                    config.execution.enable_audit_log = exec_data["enable_audit_log"]
                if "enable_metrics" in exec_data:
                    config.execution.enable_metrics = exec_data["enable_metrics"]
                if "enable_replan" in exec_data:
                    config.execution.enable_replan = exec_data["enable_replan"]
                if "confidence_threshold" in exec_data:
                    config.execution.confidence_threshold = exec_data["confidence_threshold"]

            # 更新路径配置
            if "paths" in data:
                paths_data = data["paths"]
                if "skills_dir" in paths_data:
                    config.skills_dir = Path(paths_data["skills_dir"])

            return config

        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse config file {file_path}: {e}")
        except Exception as e:
            raise ValueError(f"Failed to load config from {file_path}: {e}")

    @classmethod
    def _load_from_env(cls, config: Config) -> Config:
        """Load configuration from environment variables (without creating new Config).

        Args:
            config: Existing config to update

        Returns:
            Updated config
        """
        # LLM configuration
        if api_key := os.getenv("LLM_API_KEY"):
            config.llm.api_key = api_key
        if api_key := os.getenv("OPENAI_API_KEY"):
            config.llm.api_key = api_key
        if provider := os.getenv("LLM_PROVIDER"):
            config.llm.provider = provider
        if model := os.getenv("LLM_MODEL"):
            config.llm.model = model
        if base_url := os.getenv("LLM_BASE_URL"):
            config.llm.base_url = base_url
        if temperature := os.getenv("LLM_TEMPERATURE"):
            config.llm.temperature = float(temperature)

        # Token budget
        if limit := os.getenv("TOKEN_LIMIT"):
            config.budget.total_limit = int(limit)
        if warning := os.getenv("TOKEN_WARNING_THRESHOLD"):
            config.budget.warning_threshold = float(warning)

        # Execution settings
        if retries := os.getenv("MAX_SKILL_RETRIES"):
            config.execution.max_skill_retries = int(retries)
        if enable_replan := os.getenv("ENABLE_REPLAN"):
            config.execution.enable_replan = enable_replan.lower() == "true"

        return config

    @classmethod
    def load_profile(cls, profile_name: str) -> Config:
        """Load a named profile from config file.

        Args:
            profile_name: Name of the profile (e.g., "zhipu_glm47")

        Returns:
            Config with profile applied
        """
        # 先加载基础配置
        config = Config()

        # 首先从 config.yaml 加载（包含 profiles 定义）
        if cls.DEFAULT_CONFIG_PATH.exists():
            config = cls._load_from_file(cls.DEFAULT_CONFIG_PATH, config)

        # 查找 profile
        profile_data = None
        config_files_to_check = [cls.DEFAULT_CONFIG_PATH]
        if cls.LOCAL_CONFIG_PATH.exists():
            config_files_to_check.insert(0, cls.LOCAL_CONFIG_PATH)

        for config_file in config_files_to_check:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if "profiles" in data and profile_name in data["profiles"]:
                profile_data = data["profiles"][profile_name]
                break

        if profile_data is None:
            raise ValueError(f"Profile '{profile_name}' not found in config")

        # 应用 profile
        config = cls._apply_profile(profile_data, config)

        # 最后应用 config.local.yaml 的覆盖（如 API Key）
        if cls.LOCAL_CONFIG_PATH.exists():
            config = cls._load_from_file(cls.LOCAL_CONFIG_PATH, config)

        # 应用环境变量覆盖
        config = cls._load_from_env(config)

        return config

    @classmethod
    def _apply_profile(cls, profile_data: Dict[str, Any], config: Config) -> Config:
        """Apply profile data to config.

        Args:
            profile_data: Profile configuration dictionary
            config: Existing config to update

        Returns:
            Updated config
        """
        # 递归更新配置
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

    @classmethod
    def save_template(cls, output_path: Optional[Path] = None) -> None:
        """Save a configuration template file.

        Args:
            output_path: Optional output path (default: config.yaml.template)
        """
        if output_path is None:
            output_path = Path(__file__).parent / "config.yaml.template"

        template = {
            "llm": {
                "provider": "anthropic",
                "model": "glm-4.7",
                "api_key": "your-api-key-here",
                "base_url": "https://open.bigmodel.cn/api/anthropic",
                "temperature": 0.7,
                "max_tokens": 2000,
                "timeout": 60
            },
            "budget": {
                "total_limit": 100000,
                "warning_threshold": 0.8,
                "enable_compression": True
            },
            "execution": {
                "max_skill_retries": 2,
                "enable_streaming": True,
                "enable_audit_log": True,
                "enable_metrics": True,
                "enable_replan": True,
                "confidence_threshold": 0.5
            },
            "paths": {
                "skills_dir": "skills"
            },
            "profiles": {
                "zhipu_glm47": {
                    "llm": {
                        "provider": "anthropic",
                        "model": "glm-4.7",
                        "base_url": "https://open.bigmodel.cn/api/anthropic"
                    }
                },
                "openai_gpt4": {
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-4"
                    }
                },
                "ollama_local": {
                    "llm": {
                        "provider": "ollama",
                        "model": "llama3"
                    }
                }
            }
        }

        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(template, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        print(f"配置模板已保存到: {output_path}")
