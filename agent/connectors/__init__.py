"""数据源连接器模块

支持多种数据源类型的标准化连接器
"""

from .base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    HealthCheckResult,
    ConnectorRegistry,
    get_global_registry
)
from .database import DatabaseConnector, DatabaseConfig
from .http import HttpConnector, HttpConfig

__all__ = [
    "BaseConnector",
    "ConnectorConfig",
    "ConnectorStatus",
    "HealthCheckResult",
    "ConnectorRegistry",
    "get_global_registry",
    "DatabaseConnector",
    "DatabaseConfig",
    "HttpConnector",
    "HttpConfig",
]
