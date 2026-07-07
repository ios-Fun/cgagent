"""数据库模型"""

from sqlalchemy import Column, String, DateTime, JSON, Integer, Float, Boolean, Text
from sqlalchemy.sql import func
from app.gateway.database import Base
import uuid


class Tenant(Base):
    """租户模型"""
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    api_key = Column(String, unique=True, nullable=False, index=True)

    # LLM 配置
    llm_provider = Column(String, default="anthropic")
    llm_model = Column(String, default="glm-4.7")
    llm_api_key = Column(String)
    llm_base_url = Column(String)

    # 配置
    skill_whitelist = Column(JSON, default=list)
    rate_limit = Column(JSON, default=lambda: {"requests": 100, "window": 60})
    custom_tools = Column(JSON, default=list)

    # 状态
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "api_key": self.api_key,
            "llm_config": {
                "provider": self.llm_provider,
                "model": self.llm_model,
                "base_url": self.llm_base_url
            },
            "skill_whitelist": self.skill_whitelist,
            "rate_limit": self.rate_limit,
            "custom_tools": self.custom_tools,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Session(Base):
    """会话模型"""
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, unique=True, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)

    # 会话数据（序列化的 AgentContext）
    context_data = Column(JSON)

    # 元数据 (使用 meta_data 避免 SQLAlchemy 保留字冲突)
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_active": self.last_active.isoformat() if self.last_active else None
        }


class ChatHistory(Base):
    """聊天历史模型"""
    __tablename__ = "chat_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)

    # 消息
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)

    # 元数据 (使用 meta_data 避免 SQLAlchemy 保留字冲突)
    meta_data = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class CustomSkill(Base):
    """自定义技能模型"""
    __tablename__ = "custom_skills"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String, unique=True, nullable=False, index=True)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)

    # 技能文件内容
    skill_md = Column(Text)
    executor_py = Column(Text)
    prompt_template = Column(Text)
    schema_py = Column(Text)

    # 元数据
    description = Column(String)
    triggers = Column(JSON, default=list)
    tags = Column(JSON, default=list)

    # 状态
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "skill_id": self.skill_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "tags": self.tags,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Metric(Base):
    """指标模型"""
    __tablename__ = "metrics"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)

    # 指标类型
    metric_type = Column(String, nullable=False)  # request | token | skill | error
    metric_name = Column(String, nullable=False)

    # 值
    value = Column(Float)
    count = Column(Integer, default=1)

    # 维度
    dimensions = Column(JSON, default=dict)

    # 时间戳
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "metric_type": self.metric_type,
            "metric_name": self.metric_name,
            "value": self.value,
            "count": self.count,
            "dimensions": self.dimensions,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }
