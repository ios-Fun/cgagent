"""Global configuration for Agent Skills Framework."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    provider: str = "openai"  # openai | anthropic | ollama | zhipu
    model: str = "gpt-4"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: int = 60


@dataclass
class BudgetConfig:
    """Token budget configuration."""
    total_limit: int = 100000
    warning_threshold: float = 0.8
    enable_compression: bool = True


@dataclass
class ExecutionConfig:
    """Execution configuration."""
    max_skill_retries: int = 2
    enable_streaming: bool = True
    enable_audit_log: bool = True
    enable_metrics: bool = True
    enable_replan: bool = True
    confidence_threshold: float = 0.5


@dataclass
class Config:
    """Global configuration for the Agent Skills Framework."""
    # Project paths
    project_root: Path = field(default_factory=lambda: Path(__file__).parent)
    skills_dir: Path = field(default_factory=lambda: Path(__file__).parent / "skills")

    # LLM configuration
    llm: LLMConfig = field(default_factory=LLMConfig)

    # Token budget
    budget: BudgetConfig = field(default_factory=BudgetConfig)

    # Execution configuration
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        config = cls()

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

    def validate(self) -> bool:
        """Validate configuration."""
        if not self.llm.api_key:
            if self.llm.provider in ["openai", "anthropic", "zhipu"]:
                raise ValueError(
                    f"API key required for {self.llm.provider}. "
                    f"Set LLM_API_KEY environment variable or configure in config.local.yaml"
                )
        return True

    @classmethod
    def from_file(cls, config_path: Optional[str] = None) -> "Config":
        """Load configuration from YAML file.

        Args:
            config_path: Optional path to config file.
                        If not provided, searches for config.local.yaml, then config.yaml

        Returns:
            Config object
        """
        try:
            from config_loader import ConfigLoader
        except ImportError:
            raise ImportError("ConfigLoader not available. Install pyyaml package.")

        return ConfigLoader.load(config_path)

    @classmethod
    def from_profile(cls, profile_name: str) -> "Config":
        """Load a named profile configuration.

        Args:
            profile_name: Name of the profile (e.g., "zhipu_glm47", "openai_gpt4")

        Returns:
            Config object with profile applied
        """
        try:
            from config_loader import ConfigLoader
        except ImportError:
            raise ImportError("ConfigLoader not available. Install pyyaml package.")

        return ConfigLoader.load_profile(profile_name)
