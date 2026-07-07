"""数据源连接器基类和接口定义"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, Union
from dataclasses import dataclass
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class ConnectorStatus(Enum):
    """连接器状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class ConnectorConfig:
    """数据源配置基类"""
    name: str
    type: str  # database, http, message_queue, file, etc.
    connection_params: Dict[str, Any]
    pool_size: int = 10
    timeout: int = 30
    retry_policy: Optional[Dict[str, Any]] = None
    enabled: bool = True

    def __post_init__(self):
        if self.retry_policy is None:
            self.retry_policy = {
                "max_retries": 3,
                "backoff_factor": 2,
                "retry_on_timeout": True
            }


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    status: ConnectorStatus
    message: str
    latency_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "timestamp": self.timestamp
        }


class BaseConnector(ABC):
    """
    数据源连接器基类

    定义所有连接器必须实现的接口
    """

    def __init__(self, config: ConnectorConfig):
        self.config = config
        self._connection: Optional[Any] = None
        self._status: ConnectorStatus = ConnectorStatus.DISCONNECTED
        self._pool: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._connect_time: Optional[float] = None
        self._last_health_check: Optional[float] = None

    @property
    def is_connected(self) -> bool:
        """连接状态"""
        return self._status == ConnectorStatus.CONNECTED and self._connection is not None

    @property
    def status(self) -> ConnectorStatus:
        """获取当前状态"""
        return self._status

    @property
    def name(self) -> str:
        """连接器名称"""
        return self.config.name

    @abstractmethod
    async def connect(self) -> bool:
        """
        建立连接

        Returns:
            bool: 连接成功返回True
        """
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """
        断开连接

        Returns:
            bool: 断开成功返回True
        """
        pass

    @abstractmethod
    async def health_check(self) -> HealthCheckResult:
        """
        健康检查

        Returns:
            HealthCheckResult: 健康检查结果
        """
        pass

    @abstractmethod
    async def execute(self, operation: str, **kwargs) -> Any:
        """
        执行操作

        Args:
            operation: 操作类型或命令
            **kwargs: 操作参数

        Returns:
            操作结果
        """
        pass

    async def ensure_connected(self) -> bool:
        """确保已连接，如果未连接则自动连接"""
        if not self.is_connected:
            async with self._lock:
                if not self.is_connected:
                    return await self.connect()
        return True

    async def _retry_operation(self, operation, *args, max_retries=None, **kwargs):
        """带重试的操作执行"""
        retry_policy = self.config.retry_policy or {}
        max_retries = max_retries or retry_policy.get("max_retries", 3)
        backoff_factor = retry_policy.get("backoff_factor", 2)

        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                return await operation(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    wait_time = backoff_factor ** attempt
                    logger.warning(
                        f"操作失败，{wait_time}秒后重试 (尝试 {attempt + 1}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"操作失败，已达最大重试次数: {e}")

        raise last_exception

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, status={self._status.value})"


class ConnectorRegistry:
    """
    连接器注册表

    管理所有数据源连接器的生命周期
    """

    def __init__(self):
        self._connectors: Dict[str, BaseConnector] = {}
        self._lock = asyncio.Lock()

    async def register(self, connector: BaseConnector) -> None:
        """注册连接器"""
        async with self._lock:
            if connector.name in self._connectors:
                logger.warning(f"连接器 {connector.name} 已存在，将被覆盖")
            self._connectors[connector.name] = connector
            logger.info(f"注册连接器: {connector.name}")

    async def unregister(self, name: str) -> None:
        """注销连接器"""
        async with self._lock:
            connector = self._connectors.pop(name, None)
            if connector:
                if connector.is_connected:
                    await connector.disconnect()
                logger.info(f"注销连接器: {name}")

    async def get(self, name: str) -> Optional[BaseConnector]:
        """获取连接器"""
        return self._connectors.get(name)

    async def get_or_create(
        self,
        name: str,
        factory: callable,
        config: ConnectorConfig
    ) -> BaseConnector:
        """获取或创建连接器"""
        async with self._lock:
            connector = self._connectors.get(name)
            if connector is None:
                connector = factory(config)
                self._connectors[name] = connector
            return connector

    async def connect_all(self) -> Dict[str, bool]:
        """连接所有连接器"""
        results = {}
        for name, connector in self._connectors.items():
            try:
                results[name] = await connector.connect()
            except Exception as e:
                logger.error(f"连接器 {name} 连接失败: {e}")
                results[name] = False
        return results

    async def disconnect_all(self) -> Dict[str, bool]:
        """断开所有连接器"""
        results = {}
        for name, connector in self._connectors.items():
            try:
                results[name] = await connector.disconnect()
            except Exception as e:
                logger.error(f"连接器 {name} 断开失败: {e}")
                results[name] = False
        return results

    async def health_check_all(self) -> Dict[str, HealthCheckResult]:
        """检查所有连接器健康状态"""
        results = {}
        for name, connector in self._connectors.items():
            try:
                results[name] = await connector.health_check()
            except Exception as e:
                results[name] = HealthCheckResult(
                    status=ConnectorStatus.ERROR,
                    message=f"健康检查异常: {str(e)}",
                    timestamp=None
                )
        return results

    def list_all(self) -> List[str]:
        """列出所有连接器名称"""
        return list(self._connectors.keys())

    async def cleanup(self) -> None:
        """清理所有连接器"""
        await self.disconnect_all()
        self._connectors.clear()


# 全局连接器注册表
_global_registry: Optional[ConnectorRegistry] = None


def get_global_registry() -> ConnectorRegistry:
    """获取全局连接器注册表"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ConnectorRegistry()
    return _global_registry
