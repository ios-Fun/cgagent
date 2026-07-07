"""API 请求/响应模型"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ==================== 租户相关 ====================

class LLMConfig(BaseModel):
    """LLM 配置"""
    provider: str = "anthropic"
    model: str = "glm-4.7"
    api_key: str = ""
    base_url: Optional[str] = None


class TenantCreateRequest(BaseModel):
    """创建租户请求"""
    name: str
    tenant_id: Optional[str] = None
    plan: Optional[str] = "free"  # free, basic, pro, enterprise
    create_api_key: bool = True
    llm_config: Optional[LLMConfig] = None
    skill_whitelist: Optional[List[str]] = None
    rate_limit: Optional[Dict[str, int]] = None
    custom_tools: Optional[List[str]] = None


class TenantResponse(BaseModel):
    """租户响应"""
    tenant_id: str
    name: str
    plan: Optional[str] = None
    status: Optional[str] = None
    api_key: Optional[str] = None
    jwt_token: Optional[str] = None
    features: Optional[Dict[str, Any]] = None
    rate_limits: Optional[Dict[str, Any]] = None
    created_at: str

    class Config:
        extra = "ignore"


# ==================== 场景相关 ====================

class SceneCreateRequest(BaseModel):
    """创建场景请求"""
    name: str
    description: Optional[str] = None
    default_skills: Optional[List[str]] = None
    enabled_skills: Optional[List[str]] = None
    custom_settings: Optional[Dict[str, Any]] = None


class SceneResponse(BaseModel):
    """场景响应"""
    scene_id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    status: str
    available_skills: List[str]
    created_at: str


# ==================== 会话相关 ====================

class SessionCreateRequest(BaseModel):
    """创建会话请求"""
    user_id: Optional[str] = None
    scene_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionResponse(BaseModel):
    """会话响应"""
    session_id: str
    tenant_id: str
    scene_id: Optional[str] = None
    user_id: Optional[str] = None
    status: str
    created_at: str
    expires_at: Optional[str] = None
    total_messages: Optional[int] = None
    total_tokens: Optional[int] = None


class SessionHistoryResponse(BaseModel):
    """会话历史响应"""
    session_id: str
    messages: List[Dict[str, Any]]
    total: int


# ==================== 对话相关 ====================

class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., description="用户消息")
    user_id: str = Field(..., description="用户 ID")
    session_id: Optional[str] = Field(None, description="会话 ID，首次可为空")
    stream: bool = Field(False, description="是否流式输出")
    context: Optional[Dict[str, Any]] = Field(None, description="额外上下文")


class ChatResponse(BaseModel):
    """对话响应"""
    response: str
    session_id: str
    success: bool
    metrics: Optional[Dict[str, Any]] = None


# ==================== 技能相关 ====================

class SkillUploadRequest(BaseModel):
    """上传技能请求"""
    tenant_id: str
    skill_name: str
    files: Dict[str, str] = Field(..., description="技能文件，key 为文件名")
    description: Optional[str] = None
    triggers: Optional[List[str]] = None
    tags: Optional[List[str]] = None


class SkillResponse(BaseModel):
    """技能响应"""
    skill_id: str
    tenant_id: str
    name: str
    description: str
    triggers: List[str]
    tags: List[str]
    is_active: bool


# ==================== 工具相关 ====================

class ToolRegisterRequest(BaseModel):
    """注册工具请求"""
    tenant_id: str
    tool: Dict[str, Any]


class ToolResponse(BaseModel):
    """工具响应"""
    name: str
    description: str
    category: str


# ==================== 认证相关 ====================

class LoginRequest(BaseModel):
    """登录请求"""
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    tenant_id: str
    permissions: List[str]


class ApiKeyCreateRequest(BaseModel):
    """创建 API Key 请求"""
    name: str
    permissions: Optional[List[str]] = None
    expires_in_days: Optional[int] = 365


class ApiKeyResponse(BaseModel):
    """API Key 响应"""
    key_id: str
    name: str
    api_key: str
    created_at: str
    expires_at: Optional[str] = None


# ==================== 指标相关 ====================

class MetricsResponse(BaseModel):
    """指标响应"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_response_time_ms: float
    total_tokens_used: int
    active_sessions: int


# ==================== 健康检查 ====================

class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    timestamp: str
    database: Optional[str] = None
    redis: Optional[str] = None
