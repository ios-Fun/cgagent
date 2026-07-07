"""数据库连接器实现

支持 PostgreSQL、MySQL、SQLite 等关系型数据库
"""

import asyncio
import time
import logging
from typing import Any, Dict, Optional, List, Union
from dataclasses import dataclass

from .base import (
    BaseConnector,
    ConnectorConfig,
    ConnectorStatus,
    HealthCheckResult
)

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig(ConnectorConfig):
    """数据库连接配置"""
    connection_string: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    def __init__(
        self,
        name: str,
        type: str = "postgresql",
        connection_string: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        schema: str = "public",
        **kwargs
    ):
        super().__init__(
            name=name,
            type=type,
            connection_params=kwargs,
            **kwargs
        )
        self.connection_string = connection_string
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.schema = schema

    # 连接池配置
    min_connections: int = 1
    max_connections: int = 10
    connection_timeout: int = 30
    query_timeout: int = 30

    def build_connection_string(self) -> str:
        """构建连接字符串"""
        if self.connection_string:
            return self.connection_string

        if self.type == "postgresql":
            return (
                f"postgresql://{self.username}:{self.password}@"
                f"{self.host}:{self.port}/{self.database}"
            )
        elif self.type == "mysql":
            return (
                f"mysql+pymysql://{self.username}:{self.password}@"
                f"{self.host}:{self.port}/{self.database}"
            )
        elif self.type == "sqlite":
            return f"sqlite:///{self.database}"
        else:
            raise ValueError(f"不支持的数据库类型: {self.type}")


class DatabaseConnector(BaseConnector):
    """
    数据库连接器

    支持同步和异步数据库操作
    """

    def __init__(self, config: DatabaseConfig):
        super().__init__(config)
        self.config: DatabaseConfig = config
        self._engine = None
        self._connection_pool = None

    async def connect(self) -> bool:
        """建立数据库连接"""
        self._status = ConnectorStatus.CONNECTING
        start_time = time.time()

        try:
            # 尝试导入数据库驱动
            if self.config.type == "postgresql":
                try:
                    import asyncpg
                    self._driver = "asyncpg"
                except ImportError:
                    logger.warning("asyncpg 未安装，尝试使用 psycopg2")
                    try:
                        import psycopg2
                        from psycopg2 import pool
                        self._driver = "psycopg2"
                        self._pool_type = "psycopg2"
                    except ImportError:
                        raise ImportError("请安装 asyncpg 或 psycopg2: pip install asyncpg")

            elif self.config.type == "mysql":
                try:
                    import aiomysql
                    self._driver = "aiomysql"
                except ImportError:
                    raise ImportError("请安装 aiomysql: pip install aiomysql")

            elif self.config.type == "sqlite":
                import sqlite3
                self._driver = "sqlite3"

            else:
                raise ValueError(f"不支持的数据库类型: {self.config.type}")

            # 建立连接
            if self._driver == "asyncpg":
                self._connection = await asyncpg.connect(
                    host=self.config.host,
                    port=self.config.port,
                    user=self.config.username,
                    password=self.config.password,
                    database=self.config.database,
                    timeout=self.config.connection_timeout
                )
            elif self._driver == "aiomysql":
                self._connection = await aiomysql.connect(
                    host=self.config.host,
                    port=self.config.port,
                    user=self.config.username,
                    password=self.config.password,
                    db=self.config.database,
                    autocommit=False
                )
            elif self._driver == "sqlite3":
                self._connection = sqlite3.connect(
                    self.config.database,
                    check_same_thread=False
                )

            self._connect_time = time.time() - start_time
            self._status = ConnectorStatus.CONNECTED
            logger.info(
                f"数据库连接成功: {self.config.name} "
                f"(耗时: {self._connect_time:.3f}s)"
            )
            return True

        except Exception as e:
            self._status = ConnectorStatus.ERROR
            logger.error(f"数据库连接失败: {e}")
            raise

    async def disconnect(self) -> bool:
        """断开数据库连接"""
        try:
            if self._connection:
                if self._driver == "asyncpg":
                    await self._connection.close()
                elif self._driver == "aiomysql":
                    self._connection.close()
                elif self._driver == "sqlite3":
                    self._connection.close()

                self._connection = None
                self._status = ConnectorStatus.DISCONNECTED
                logger.info(f"数据库连接已断开: {self.config.name}")
                return True
            return False
        except Exception as e:
            logger.error(f"断开数据库连接失败: {e}")
            return False

    async def health_check(self) -> HealthCheckResult:
        """健康检查"""
        start_time = time.time()

        try:
            if not self.is_connected:
                return HealthCheckResult(
                    status=ConnectorStatus.DISCONNECTED,
                    message="数据库未连接",
                    latency_ms=None,
                    timestamp=None
                )

            # 执行简单查询检查连接
            if self._driver == "asyncpg":
                await self._connection.fetchval("SELECT 1")
            elif self._driver == "aiomysql":
                async with self._connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
            elif self._driver == "sqlite3":
                cursor = self._connection.cursor()
                cursor.execute("SELECT 1")

            latency = (time.time() - start_time) * 1000

            return HealthCheckResult(
                status=ConnectorStatus.CONNECTED,
                message="数据库连接正常",
                latency_ms=round(latency, 2),
                details={
                    "database": self.config.database,
                    "type": self.config.type,
                    "driver": self._driver
                },
                timestamp=None
            )

        except Exception as e:
            return HealthCheckResult(
                status=ConnectorStatus.ERROR,
                message=f"健康检查失败: {str(e)}",
                latency_ms=None,
                timestamp=None
            )

    async def execute(
        self,
        operation: str,
        **kwargs
    ) -> Any:
        """
        执行数据库操作

        Args:
            operation: 操作类型 (query, execute, fetch_one, fetch_many)
            **kwargs: 操作参数
                - query: SQL查询语句
                - params: 查询参数
                - limit: 返回记录数限制
        """
        await self.ensure_connected()

        query = kwargs.get("query", "")
        params = kwargs.get("params", None)
        limit = kwargs.get("limit", None)

        try:
            if operation == "fetch_one":
                return await self._fetch_one(query, params)
            elif operation == "fetch_many":
                return await self._fetch_many(query, params, limit)
            elif operation == "execute":
                return await self._execute(query, params)
            elif operation == "query":
                return await self._fetch_many(query, params, limit)
            else:
                raise ValueError(f"不支持的操作类型: {operation}")

        except Exception as e:
            logger.error(f"数据库操作失败: {e}")
            raise

    async def _fetch_one(
        self,
        query: str,
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """获取单条记录"""
        if self._driver == "asyncpg":
            row = await self._connection.fetchrow(query, *self._prepare_params(params))
            return dict(row) if row else None

        elif self._driver == "aiomysql":
            async with self._connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, params or ())
                row = await cursor.fetchone()
                return row

        elif self._driver == "sqlite3":
            cursor = self._connection.cursor()
            cursor.execute(query, params or ())
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
            return None

    async def _fetch_many(
        self,
        query: str,
        params: Optional[Dict] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """获取多条记录"""
        if limit:
            query = f"{query} LIMIT {limit}"

        if self._driver == "asyncpg":
            rows = await self._connection.fetch(query, *self._prepare_params(params))
            return [dict(row) for row in rows]

        elif self._driver == "aiomysql":
            async with self._connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, params or ())
                rows = await cursor.fetchall()
                return rows

        elif self._driver == "sqlite3":
            cursor = self._connection.cursor()
            cursor.execute(query, params or ())
            rows = cursor.fetchall()
            if rows:
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in rows]
            return []

    async def _execute(
        self,
        query: str,
        params: Optional[Dict] = None
    ) -> int:
        """执行SQL语句（INSERT, UPDATE, DELETE）"""
        if self._driver == "asyncpg":
            result = await self._connection.execute(query, *self._prepare_params(params))
            return result

        elif self._driver == "aiomysql":
            async with self._connection.cursor() as cursor:
                await cursor.execute(query, params or ())
                await self._connection.commit()
                return cursor.rowcount

        elif self._driver == "sqlite3":
            cursor = self._connection.cursor()
            cursor.execute(query, params or ())
            self._connection.commit()
            return cursor.rowcount

    def _prepare_params(self, params: Optional[Union[Dict, List, tuple]]) -> list:
        """准备查询参数"""
        if params is None:
            return []
        if isinstance(params, dict):
            return list(params.values())
        if isinstance(params, (list, tuple)):
            return list(params)
        return [params]


# 便捷函数
async def create_database_connector(
    name: str,
    db_type: str = "postgresql",
    **connection_params
) -> DatabaseConnector:
    """
    创建数据库连接器

    Args:
        name: 连接器名称
        db_type: 数据库类型 (postgresql, mysql, sqlite)
        **connection_params: 连接参数
            - host: 主机地址
            - port: 端口
            - database: 数据库名
            - username: 用户名
            - password: 密码
            - connection_string: 完整连接字符串（可选）

    Returns:
        DatabaseConnector 实例
    """
    config = DatabaseConfig(
        name=name,
        type=db_type,
        connection_params=connection_params,
        **connection_params
    )
    connector = DatabaseConnector(config)
    await connector.connect()
    return connector
