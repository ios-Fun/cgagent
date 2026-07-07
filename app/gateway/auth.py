# """
# API 认证授权模块
#
# 提供 JWT Token 认证、API Key 验证、权限控制等功能。
# """
#
# import jwt
# import secrets
# import time
# from datetime import datetime, timedelta
# from typing import Dict, List, Optional, Any
# from dataclasses import dataclass
# from enum import Enum
# import logging
#
# from app.gateway.config import settings
#
# logger = logging.getLogger(__name__)
#
#
# class Permission(Enum):
#     """权限枚举"""
#     # 智能体相关
#     AGENT_CHAT = "agent:chat"
#     AGENT_ADMIN = "agent:admin"
#
#     # Skills 相关
#     SKILLS_READ = "skills:read"
#     SKILLS_WRITE = "skills:write"
#     SKILLS_DELETE = "skills:delete"
#
#     # 租户相关
#     TENANTS_READ = "tenants:read"
#     TENANTS_WRITE = "tenants:write"
#     TENANTS_DELETE = "tenants:delete"
#
#     # 监控相关
#     METRICS_READ = "metrics:read"
#
#     # 审计相关
#     AUDIT_READ = "audit:read"
#
#     # 会话相关
#     SESSIONS_READ = "sessions:read"
#     SESSIONS_WRITE = "sessions:write"
#     SESSIONS_DELETE = "sessions:delete"
#
#
# @dataclass
# class TokenPayload:
#     """Token 载荷"""
#     tenant_id: str
#     user_id: Optional[str] = None
#     permissions: List[str] = None
#     exp: Optional[int] = None
#     iat: Optional[int] = None
#
#     def __post_init__(self):
#         if self.permissions is None:
#             self.permissions = []
#
#     def has_permission(self, permission: Permission) -> bool:
#         """检查是否有指定权限"""
#         return permission.value in self.permissions or "admin" in self.permissions
#
#
# @dataclass
# class APIKeyInfo:
#     """API Key 信息"""
#     key_id: str
#     tenant_id: str
#     name: str
#     permissions: List[str]
#     created_at: datetime
#     expires_at: Optional[datetime] = None
#     is_active: bool = True
#
#
# class JWTManager:
#     """JWT 管理器"""
#
#     def __init__(
#         self,
#         secret_key: str = None,
#         algorithm: str = None,
#         access_token_expire_minutes: int = None,
#     ):
#         self.secret_key = secret_key or settings.SECRET_KEY
#         self.algorithm = algorithm or settings.ALGORITHM
#         self.access_token_expire_minutes = access_token_expire_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
#
#     def create_access_token(
#         self,
#         tenant_id: str,
#         user_id: Optional[str] = None,
#         permissions: Optional[List[str]] = None,
#         additional_claims: Optional[Dict[str, Any]] = None,
#     ) -> str:
#         """
#         创建访问令牌
#
#         Args:
#             tenant_id: 租户 ID
#             user_id: 用户 ID
#             permissions: 权限列表
#             additional_claims: 额外的声明
#
#         Returns:
#             JWT Token
#         """
#         now = datetime.utcnow()
#         expire = now + timedelta(minutes=self.access_token_expire_minutes)
#
#         payload = {
#             "tenant_id": tenant_id,
#             "user_id": user_id,
#             "permissions": permissions or [],
#             "iat": int(now.timestamp()),
#             "exp": int(expire.timestamp()),
#             **(additional_claims or {}),
#         }
#
#         token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
#         return token
#
#     def decode_token(self, token: str) -> Optional[TokenPayload]:
#         """
#         解码并验证令牌
#
#         Args:
#             token: JWT Token
#
#         Returns:
#             Token 载荷
#         """
#         try:
#             payload = jwt.decode(
#                 token,
#                 self.secret_key,
#                 algorithms=[self.algorithm],
#             )
#
#             return TokenPayload(
#                 tenant_id=payload.get("tenant_id", ""),
#                 user_id=payload.get("user_id"),
#                 permissions=payload.get("permissions", []),
#                 exp=payload.get("exp"),
#                 iat=payload.get("iat"),
#             )
#
#         except jwt.ExpiredSignatureError:
#             logger.warning("Token 已过期")
#             return None
#         except jwt.InvalidTokenError as e:
#             logger.warning(f"无效的 Token: {e}")
#             return None
#
#     def verify_token(self, token: str) -> bool:
#         """
#         验证令牌
#
#         Args:
#             token: JWT Token
#
#         Returns:
#             是否有效
#         """
#         payload = self.decode_token(token)
#         return payload is not None
#
#
# class APIKeyManager:
#     """API Key 管理器"""
#
#     def __init__(self):
#         self._keys: Dict[str, APIKeyInfo] = {}
#         self._key_to_tenant: Dict[str, str] = {}
#
#     def generate_api_key(self, prefix: str = "sk_agent") -> str:
#         """
#         生成 API Key
#
#         Args:
#             prefix: Key 前缀
#
#         Returns:
#             API Key
#         """
#         random_part = secrets.token_urlsafe(32)
#         return f"{prefix}_{random_part}"
#
#     def create_api_key(
#         self,
#         tenant_id: str,
#         name: str,
#         permissions: List[str],
#         expires_in_days: Optional[int] = None,
#     ) -> str:
#         """
#         创建 API Key
#
#         Args:
#             tenant_id: 租户 ID
#             name: Key 名称
#             permissions: 权限列表
#             expires_in_days: 过期天数
#
#         Returns:
#             API Key
#         """
#         api_key = self.generate_api_key()
#         key_id = secrets.token_hex(8)
#
#         now = datetime.utcnow()
#         expires_at = now + timedelta(days=expires_in_days) if expires_in_days else None
#
#         key_info = APIKeyInfo(
#             key_id=key_id,
#             tenant_id=tenant_id,
#             name=name,
#             permissions=permissions,
#             created_at=now,
#             expires_at=expires_at,
#             is_active=True,
#         )
#
#         self._keys[api_key] = key_info
#         self._key_to_tenant[api_key] = tenant_id
#
#         logger.info(f"创建 API Key: {key_id} for tenant {tenant_id}")
#         return api_key
#
#     def verify_api_key(self, api_key: str) -> Optional[APIKeyInfo]:
#         """
#         验证 API Key
#
#         Args:
#             api_key: API Key
#
#         Returns:
#             API Key 信息
#         """
#         key_info = self._keys.get(api_key)
#         if not key_info:
#             return None
#
#         # 检查是否激活
#         if not key_info.is_active:
#             logger.warning(f"API Key 已被禁用: {key_info.key_id}")
#             return None
#
#         # 检查是否过期
#         if key_info.expires_at and datetime.utcnow() > key_info.expires_at:
#             logger.warning(f"API Key 已过期: {key_info.key_id}")
#             return None
#
#         return key_info
#
#     def revoke_api_key(self, api_key: str) -> bool:
#         """
#         吊销 API Key
#
#         Args:
#             api_key: API Key
#
#         Returns:
#             是否成功
#         """
#         key_info = self._keys.get(api_key)
#         if not key_info:
#             return False
#
#         key_info.is_active = False
#         logger.info(f"吊销 API Key: {key_info.key_id}")
#         return True
#
#     def get_tenant_api_keys(self, tenant_id: str) -> List[APIKeyInfo]:
#         """
#         获取租户的所有 API Key
#
#         Args:
#             tenant_id: 租户 ID
#
#         Returns:
#             API Key 信息列表
#         """
#         return [
#             key_info for key_info in self._keys.values()
#             if key_info.tenant_id == tenant_id
#         ]
#
#
# class PermissionChecker:
#     """权限检查器"""
#
#     def __init__(self):
#         self._role_permissions: Dict[str, List[Permission]] = {
#             "admin": list(Permission),
#             "user": [
#                 Permission.AGENT_CHAT,
#                 Permission.SKILLS_READ,
#                 Permission.SESSIONS_READ,
#                 Permission.SESSIONS_WRITE,
#             ],
#             "readonly": [
#                 Permission.SKILLS_READ,
#                 Permission.TENANTS_READ,
#                 Permission.METRICS_READ,
#                 Permission.AUDIT_READ,
#                 Permission.SESSIONS_READ,
#             ],
#         }
#
#     def check_permission(
#         self,
#         permissions: List[str],
#         required_permission: Permission,
#     ) -> bool:
#         """
#         检查是否有权限
#
#         Args:
#             permissions: 用户权限列表
#             required_permission: 需要的权限
#
#         Returns:
#             是否有权限
#         """
#         # admin 拥有所有权限
#         if "admin" in permissions:
#             return True
#
#         return required_permission.value in permissions
#
#     def check_permissions(
#         self,
#         user_permissions: List[str],
#         required_permissions: List[Permission],
#         require_all: bool = False,
#     ) -> bool:
#         """
#         检查多个权限
#
#         Args:
#             user_permissions: 用户权限列表
#             required_permissions: 需要的权限列表
#             require_all: 是否需要全部满足
#
#         Returns:
#             是否有权限
#         """
#         # admin 拥有所有权限
#         if "admin" in user_permissions:
#             return True
#
#         if require_all:
#             return all(
#                 perm.value in user_permissions
#                 for perm in required_permissions
#             )
#         else:
#             return any(
#                 perm.value in user_permissions
#                 for perm in required_permissions
#             )
#
#     def get_role_permissions(self, role: str) -> List[Permission]:
#         """
#         获取角色的权限
#
#         Args:
#             role: 角色名称
#
#         Returns:
#             权限列表
#         """
#         return self._role_permissions.get(role, [])
#
#     def add_role(self, role: str, permissions: List[Permission]):
#         """
#         添加角色
#
#         Args:
#             role: 角色名称
#             permissions: 权限列表
#         """
#         self._role_permissions[role] = permissions
#
#
# # 全局单例
# _jwt_manager: Optional[JWTManager] = None
# _api_key_manager: Optional[APIKeyManager] = None
# _permission_checker: Optional[PermissionChecker] = None
#
#
# def get_jwt_manager() -> JWTManager:
#     """获取 JWT 管理器单例"""
#     global _jwt_manager
#     if _jwt_manager is None:
#         _jwt_manager = JWTManager()
#     return _jwt_manager
#
#
# def get_api_key_manager() -> APIKeyManager:
#     """获取 API Key 管理器单例"""
#     global _api_key_manager
#     if _api_key_manager is None:
#         _api_key_manager = APIKeyManager()
#     return _api_key_manager
#
#
# def get_permission_checker() -> PermissionChecker:
#     """获取权限检查器单例"""
#     global _permission_checker
#     if _permission_checker is None:
#         _permission_checker = PermissionChecker()
#     return _permission_checker
#
#
# # 便捷函数
# def create_token_for_tenant(
#     tenant_id: str,
#     permissions: Optional[List[str]] = None,
# ) -> str:
#     """为租户创建 Token"""
#     return get_jwt_manager().create_access_token(
#         tenant_id=tenant_id,
#         permissions=permissions,
#     )
#
#
# def verify_token_or_api_key(
#     token: Optional[str] = None,
#     api_key: Optional[str] = None,
# ) -> Optional[TokenPayload]:
#     """
#     验证 Token 或 API Key
#
#     Args:
#         token: JWT Token
#         api_key: API Key
#
#     Returns:
#         Token 载荷
#     """
#     # 优先验证 Token
#     if token:
#         payload = get_jwt_manager().decode_token(token)
#         if payload:
#             return payload
#
#     # 尝试验证 API Key
#     if api_key:
#         key_info = get_api_key_manager().verify_api_key(api_key)
#         if key_info:
#             return TokenPayload(
#                 tenant_id=key_info.tenant_id,
#                 permissions=key_info.permissions,
#             )
#
#     return None
#
#
# def require_permission(required_permission: Permission):
#     """
#     权限装饰器工厂
#
#     用于装饰需要特定权限的端点。
#
#     Args:
#         required_permission: 需要的权限
#
#     Returns:
#         装饰器函数
#     """
#     def decorator(func):
#         async def wrapper(*args, **kwargs):
#             # 从 kwargs 中获取 token_payload
#             token_payload = kwargs.get("token_payload")
#             if not token_payload:
#                 from fastapi import HTTPException
#                 raise HTTPException(status_code=401, detail="未认证")
#
#             # 检查权限
#             if not get_permission_checker().check_permission(
#                 token_payload.permissions,
#                 required_permission,
#             ):
#                 from fastapi import HTTPException
#                 raise HTTPException(status_code=403, detail="权限不足")
#
#             return await func(*args, **kwargs)
#
#         return wrapper
#
#     return decorator
