"""HTTP API连接器实现

支持 RESTful API 调用
"""

import asyncio
import time
import json
import logging
from typing import Any, Dict, Optional, List, Union
from dataclasses import dataclass
from urllib.parse import urljoin

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    try:
        import aiohttp
    except ImportError:
        aiohttp = None

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp as aiohttp_type

from .base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    HealthCheckResult
)

logger = logging.getLogger(__name__)


@dataclass
class HttpConfig(ConnectorConfig):
    """HTTP连接配置"""
    base_url: str = ""
    timeout: int = 30
    max_connections: int = 100
    max_keepalive_connections: int = 20

    # 认证配置
    auth_type: Optional[str] = None  # bearer, api_key, basic, oauth2
    api_key: Optional[str] = None
    api_key_header: str = "X-API-Key"
    bearer_token: Optional[str] = None
    basic_username: Optional[str] = None
    basic_password: Optional[str] = None

    # 重试配置
    max_retries: int = 3
    retry_on_status: List[int] = None

    # 默认请求头
    default_headers: Dict[str, str] = None

    def __init__(
        self,
        name: str,
        type: str = "http",
        base_url: str = "",
        timeout: int = 30,
        max_connections: int = 100,
        max_keepalive_connections: int = 20,
        auth_type: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_header: str = "X-API-Key",
        bearer_token: Optional[str] = None,
        basic_username: Optional[str] = None,
        basic_password: Optional[str] = None,
        max_retries: int = 3,
        retry_on_status: Optional[List[int]] = None,
        default_headers: Optional[Dict[str, str]] = None,
        **kwargs
    ):
        # 先初始化父类
        ConnectorConfig.__init__(
            self,
            name=name,
            type=type,
            connection_params=kwargs,
            timeout=timeout
        )
        self.base_url = base_url
        self.timeout = timeout
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections
        self.auth_type = auth_type
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.bearer_token = bearer_token
        self.basic_username = basic_username
        self.basic_password = basic_password
        self.max_retries = max_retries
        self.retry_on_status = retry_on_status or [500, 502, 503, 504]
        self.default_headers = default_headers or {
            "Content-Type": "application/json",
            "User-Agent": "Agent-Skills-Framework/1.0"
        }

    def __post_init__(self):
        super().__post_init__()
        if self.retry_on_status is None:
            self.retry_on_status = [500, 502, 503, 504]
        if self.default_headers is None:
            self.default_headers = {
                "Content-Type": "application/json",
                "User-Agent": "Agent-Skills-Framework/1.0"
        }


class HttpConnector(BaseConnector):
    """
    HTTP API 连接器

    支持 RESTful API 调用，包含认证、重试、限流等功能
    """

    def __init__(self, config: HttpConfig):
        super().__init__(config)
        self.config: HttpConfig = config
        self._client: Optional[Union[httpx.AsyncClient, aiohttp.ClientSession]] = None
        self._client_type: Optional[str] = None

    async def connect(self) -> bool:
        """建立HTTP连接（初始化客户端）"""
        self._status = ConnectorStatus.CONNECTING
        start_time = time.time()

        try:
            headers = self._build_headers()

            if HAS_HTTPX:
                self._client = httpx.AsyncClient(
                    base_url=self.config.base_url,
                    headers=headers,
                    timeout=self.config.timeout,
                    limits=httpx.Limits(
                        max_connections=self.config.max_connections,
                        max_keepalive_connections=self.config.max_keepalive_connections
                    )
                )
                self._client_type = "httpx"
            else:
                self._client = aiohttp.ClientSession(
                    base_url=self.config.base_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.config.timeout)
                )
                self._client_type = "aiohttp"

            self._connect_time = time.time() - start_time
            self._status = ConnectorStatus.CONNECTED
            logger.info(
                f"HTTP客户端初始化成功: {self.config.name} "
                f"(类型: {self._client_type}, 耗时: {self._connect_time:.3f}s)"
            )
            return True

        except Exception as e:
            self._status = ConnectorStatus.ERROR
            logger.error(f"HTTP客户端初始化失败: {e}")
            raise

    async def disconnect(self) -> bool:
        """关闭HTTP客户端"""
        try:
            if self._client:
                await self._client.close()
                self._client = None
                self._status = ConnectorStatus.DISCONNECTED
                logger.info(f"HTTP客户端已关闭: {self.config.name}")
                return True
            return False
        except Exception as e:
            logger.error(f"关闭HTTP客户端失败: {e}")
            return False

    async def health_check(self) -> HealthCheckResult:
        """健康检查"""
        start_time = time.time()

        try:
            if not self.is_connected:
                return HealthCheckResult(
                    status=ConnectorStatus.DISCONNECTED,
                    message="HTTP客户端未连接",
                    latency_ms=None
                )

            # 尝试简单的HEAD请求
            try:
                if self._client_type == "httpx":
                    response = await self._client.head("/", timeout=5)
                else:
                    async with self._client.head("/", timeout=5) as response:
                        pass
            except:
                # 如果HEAD失败，尝试GET
                pass  # 继续检查客户端状态

            latency = (time.time() - start_time) * 1000

            return HealthCheckResult(
                status=ConnectorStatus.CONNECTED,
                message="HTTP客户端正常",
                latency_ms=round(latency, 2),
                details={
                    "base_url": self.config.base_url,
                    "client_type": self._client_type
                }
            )

        except Exception as e:
            return HealthCheckResult(
                status=ConnectorStatus.ERROR,
                message=f"健康检查失败: {str(e)}",
                latency_ms=None
            )

    async def execute(
        self,
        operation: str,
        **kwargs
    ) -> Any:
        """
        执行HTTP请求

        Args:
            operation: HTTP方法 (get, post, put, delete, patch)
            **kwargs: 请求参数
                - path: 请求路径
                - params: URL参数
                - data: 请求体数据
                - json: JSON请求体
                - headers: 额外请求头
        """
        await self.ensure_connected()

        method = operation.lower()
        path = kwargs.get("path", "")
        params = kwargs.get("params", None)
        data = kwargs.get("data", None)
        json_data = kwargs.get("json", None)
        headers = kwargs.get("headers", {})

        try:
            return await self._request(
                method=method,
                path=path,
                params=params,
                data=data,
                json_data=json_data,
                headers=headers
            )
        except Exception as e:
            logger.error(f"HTTP请求失败: {e}")
            raise

    async def get(
        self,
        path: str = "",
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Any:
        """GET请求"""
        return await self.execute("get", path=path, params=params, headers=headers)

    async def post(
        self,
        path: str = "",
        data: Optional[Any] = None,
        json: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Any:
        """POST请求"""
        return await self.execute("post", path=path, data=data, json=json, headers=headers)

    async def put(
        self,
        path: str = "",
        data: Optional[Any] = None,
        json: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Any:
        """PUT请求"""
        return await self.execute("put", path=path, data=data, json=json, headers=headers)

    async def delete(
        self,
        path: str = "",
        params: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Any:
        """DELETE请求"""
        return await self.execute("delete", path=path, params=params, headers=headers)

    async def patch(
        self,
        path: str = "",
        data: Optional[Any] = None,
        json: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Any:
        """PATCH请求"""
        return await self.execute("patch", path=path, data=data, json=json, headers=headers)

    async def _request(
        self,
        method: str,
        path: str = "",
        params: Optional[Dict] = None,
        data: Optional[Any] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None
    ) -> Any:
        """执行实际的HTTP请求"""
        request_headers = {**self._build_headers()}
        if headers:
            request_headers.update(headers)

        full_url = urljoin(self.config.base_url, path)

        # 使用重试机制
        max_retries = self.config.max_retries
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                if self._client_type == "httpx":
                    response = await self._client.request(
                        method=method,
                        url=full_url,
                        params=params,
                        content=data,
                        json=json_data,
                        headers=request_headers
                    )

                    # 检查是否需要重试
                    if attempt < max_retries and response.status_code in self.config.retry_on_status:
                        await asyncio.sleep(2 ** attempt)
                        continue

                    response.raise_for_status()
                    return self._parse_response(response)

                else:  # aiohttp
                    async with self._client.request(
                        method=method,
                        url=full_url,
                        params=params,
                        data=data,
                        json=json_data,
                        headers=request_headers
                    ) as response:

                        # 检查是否需要重试
                        if attempt < max_retries and response.status in self.config.retry_on_status:
                            await asyncio.sleep(2 ** attempt)
                            continue

                        response.raise_for_status()
                        return await self._parse_response_aiohttp(response)

            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

        raise last_exception

    def _build_headers(self) -> Dict[str, str]:
        """构建请求头"""
        headers = self.config.default_headers.copy()

        # 添加认证头
        if self.config.auth_type == "bearer" and self.config.bearer_token:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"
        elif self.config.auth_type == "api_key" and self.config.api_key:
            headers[self.config.api_key_header] = self.config.api_key
        elif self.config.auth_type == "basic":
            import base64
            credentials = f"{self.config.basic_username}:{self.config.basic_password}"
            encoded = base64.b64encode(credentials.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return headers

    def _parse_response(self, response: httpx.Response) -> Any:
        """解析httpx响应"""
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            return response.json()
        else:
            return response.text

    async def _parse_response_aiohttp(self, response) -> Any:
        """解析aiohttp响应"""
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            return await response.json()
        else:
            return await response.text()


# 便捷函数
async def create_http_connector(
    name: str,
    base_url: str,
    auth_type: Optional[str] = None,
    api_key: Optional[str] = None,
    bearer_token: Optional[str] = None,
    **kwargs
) -> HttpConnector:
    """
    创建HTTP连接器

    Args:
        name: 连接器名称
        base_url: API基础URL
        auth_type: 认证类型 (bearer, api_key, basic)
        api_key: API密钥
        bearer_token: Bearer令牌
        **kwargs: 其他配置参数

    Returns:
        HttpConnector 实例
    """
    config = HttpConfig(
        name=name,
        base_url=base_url,
        auth_type=auth_type,
        api_key=api_key,
        bearer_token=bearer_token,
        connection_params=kwargs,
        **kwargs
    )
    connector = HttpConnector(config)
    await connector.connect()
    return connector
