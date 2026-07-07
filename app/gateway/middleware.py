"""API 中间件"""

import time
import hashlib
import hmac
from typing import Callable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None

from app.gateway.config import settings
from app.gateway.exceptions import AuthenticationException, RateLimitExceededException

# 导入多租户模块（处理可能缺失的函数）
try:
    from agent.multi_tenant import TenantManager
except ImportError:
    TenantManager = None

# 存根函数用于处理缺失的认证函数
def _stub_function(*args, **kwargs):
    return None

try:
    from agent.multi_tenant import get_jwt_manager
except ImportError:
    get_jwt_manager = _stub_function

try:
    from agent.multi_tenant import get_api_key_manager
except ImportError:
    get_api_key_manager = _stub_function

try:
    from agent.multi_tenant import verify_token_or_api_key
except ImportError:
    verify_token_or_api_key = _stub_function


class TenantMiddleware(BaseHTTPMiddleware):
    """租户识别中间件"""

    def __init__(self, app: ASGIApp, tenant_manager: TenantManager):
        super().__init__(app)
        self.tenant_manager = tenant_manager

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """从请求中提取租户信息并添加到 state"""
        # 从 X-Tenant-ID 头获取租户 ID
        tenant_id = request.headers.get("X-Tenant-ID")

        # 如果没有，尝试从 API Key 或 Token 派生
        if not tenant_id:
            # 从 Authorization 头获取认证信息
            auth_header = request.headers.get("Authorization", "")

            if auth_header.startswith("Bearer "):
                token = auth_header.replace("Bearer ", "")
                if verify_token_or_api_key is not _stub_function:
                    payload = verify_token_or_api_key(token=token)
                    if payload and hasattr(payload, 'tenant_id'):
                        tenant_id = payload.tenant_id
            elif auth_header.startswith("ApiKey "):
                api_key = auth_header.replace("ApiKey ", "")
                if get_api_key_manager is not _stub_function:
                    key_manager = get_api_key_manager()
                    if key_manager and hasattr(key_manager, 'verify_api_key'):
                        key_info = key_manager.verify_api_key(api_key)
                        if key_info and hasattr(key_info, 'tenant_id'):
                            tenant_id = key_info.tenant_id

        # 设置默认租户
        request.state.tenant_id = tenant_id or settings.DEFAULT_TENANT_ID

        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """验证 API Key 或 JWT Token"""
        # 跳过健康检查和文档路径
        if request.url.path in ["/", "/docs", "/redoc", "/health", "/api/v1/health"]:
            return await call_next(request)

        # 获取认证信息
        auth_header = request.headers.get("Authorization", "")

        payload = None

        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            payload = verify_token_or_api_key(token=token)
        elif auth_header.startswith("ApiKey "):
            api_key = auth_header.replace("ApiKey ", "")
            payload = verify_token_or_api_key(api_key=api_key)

        # 检查是否是开发环境
        if not payload:
            if settings.DEBUG:
                return await call_next(request)
            raise AuthenticationException()

        # 存储验证结果到 state
        request.state.token_payload = payload
        request.state.tenant_id = payload.tenant_id

        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._redis = None

    async def get_redis(self):
        """获取 Redis 连接"""
        if self._redis is None:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """限流检查"""
        # 跳过健康检查
        if request.url.path in ["/health", "/api/v1/health"]:
            return await call_next(request)

        # 如果 Redis 不可用，跳过限流
        if not REDIS_AVAILABLE:
            return await call_next(request)

        try:
            r = await self.get_redis()
            tenant_id = request.state.tenant_id or "default"
            key = f"ratelimit:{tenant_id}"

            # 获取当前计数
            current = await r.incr(key)
            if current == 1:
                await r.expire(key, settings.RATE_LIMIT_WINDOW)

            if current > settings.RATE_LIMIT_REQUESTS:
                raise RateLimitExceededException(retry_after=settings.RATE_LIMIT_WINDOW)

        except redis.RedisError:
            # Redis 不可用时，跳过限流
            pass
        except RateLimitExceededException:
            raise
        except Exception:
            # 其他异常，跳过限流
            pass

        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    """日志中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """记录请求日志"""
        start_time = time.time()

        # 安全地获取租户ID
        tenant_id = getattr(request.state, 'tenant_id', 'N/A')

        # 记录请求
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
              f"{request.method} {request.url.path} "
              f"Tenant: {tenant_id}")

        # 处理请求
        response = await call_next(request)

        # 记录响应时间
        process_time = (time.time() - start_time) * 1000
        response.headers["X-Process-Time"] = str(process_time)

        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
              f"Response: {response.status_code} "
              f"Time: {process_time:.2f}ms")

        return response


class WebhookSignatureMiddleware(BaseHTTPMiddleware):
    """Webhook 签名验证中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """验证 Webhook 签名"""
        # 只对 Webhook 路径进行签名验证
        if "/webhook" not in request.url.path:
            return await call_next(request)

        # 获取签名
        signature = request.headers.get("X-Signature", "")
        if not signature:
            return Response("Missing signature", status_code=401)

        # 获取请求体
        body = await request.body()

        # 验证签名
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode(),
            body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_sig):
            return Response("Invalid signature", status_code=401)

        return await call_next(request)
