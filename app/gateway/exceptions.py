"""API 异常定义"""


class AgentException(Exception):
    """智能体框架基础异常"""

    def __init__(self, message: str, code: str = "AGENT_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class TenantNotFoundException(AgentException):
    """租户不存在异常"""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(
            message=f"租户不存在: {tenant_id}",
            code="TENANT_NOT_FOUND"
        )


class TenantAlreadyExistsException(AgentException):
    """租户已存在异常"""

    def __init__(self, tenant_id: str):
        super().__init__(
            message=f"租户已存在: {tenant_id}",
            code="TENANT_ALREADY_EXISTS"
        )


class AuthenticationException(AgentException):
    """认证异常"""

    def __init__(self, message: str = "认证失败"):
        super().__init__(
            message=message,
            code="AUTHENTICATION_FAILED"
        )


class RateLimitExceededException(AgentException):
    """限流异常"""

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(
            message="请求频率超限，请稍后再试",
            code="RATE_LIMIT_EXCEEDED"
        )


class SessionNotFoundException(AgentException):
    """会话不存在异常"""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"会话不存在: {session_id}",
            code="SESSION_NOT_FOUND"
        )


class SkillNotFoundException(AgentException):
    """技能不存在异常"""

    def __init__(self, skill_name: str):
        super().__init__(
            message=f"技能不存在: {skill_name}",
            code="SKILL_NOT_FOUND"
        )


class InvalidRequestException(AgentException):
    """无效请求异常"""

    def __init__(self, message: str = "无效的请求"):
        super().__init__(
            message=message,
            code="INVALID_REQUEST"
        )
