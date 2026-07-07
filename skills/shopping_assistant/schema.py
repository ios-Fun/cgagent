"""智能导购助手数据结构"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


class DialogueState(Enum):
    """对话状态"""
    GREETING = "greeting"           # 问候阶段
    NEED_COLLECTING = "need_collecting"  # 需求收集阶段
    RECOMMENDING = "recommending"   # 推荐阶段
    COMPARING = "comparing"         # 对比阶段
    INQUIRING = "inquiring"         # 咨询阶段
    CLOSED = "closed"               # 对话结束


class UserIntent(Enum):
    """用户意图"""
    RECOMMEND = "recommend"         # 求推荐
    COMPARE = "compare"             # 对比商品
    INQUIRE = "inquire"             # 商品咨询
    ORDER_QUERY = "order_query"     # 订单查询
    RETURN_EXCHANGE = "return_exchange"  # 退换货
    CHITCHAT = "chitchat"           # 闲聊


@dataclass
class Product:
    """商品信息"""
    id: str
    name: str
    brand: str
    price: float
    category: str
    description: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    rating: float = 0.0
    sales: int = 0
    stock: int = 0
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "price": self.price,
            "category": self.category,
            "description": self.description,
            "attributes": self.attributes,
            "rating": self.rating,
            "sales": self.sales,
            "stock": self.stock,
            "tags": self.tags
        }

    def to_display_text(self) -> str:
        """生成展示文本"""
        attrs = []
        for key, value in self.attributes.items():
            if key in ["processor", "screen", "battery", "gpu", "ram", "storage"]:
                attrs.append(f"{key}: {value}")

        return (
            f"【{self.name}】\n"
            f"品牌: {self.brand} | 价格: ¥{self.price}\n"
            f"评分: {self.rating}⭐ | 销量: {self.sales}\n"
            f"配置: {', '.join(attrs[:5])}\n"
            f"描述: {self.description}"
        )


@dataclass
class UserPreference:
    """用户偏好"""
    category: Optional[str] = None
    brands: List[str] = field(default_factory=list)
    price_range: Optional[Dict[str, float]] = None  # {"min": 0, "max": 10000}
    use_case: Optional[str] = None
    priority_features: List[str] = field(default_factory=list)
    budget_sensitive: bool = True

    def is_complete(self) -> bool:
        """判断偏好是否完整"""
        return self.category is not None and self.price_range is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "brands": self.brands,
            "price_range": self.price_range,
            "use_case": self.use_case,
            "priority_features": self.priority_features,
            "budget_sensitive": self.budget_sensitive
        }


@dataclass
class Message:
    """对话消息"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class Conversation:
    """对话会话"""
    session_id: str
    user_id: str
    messages: List[Message] = field(default_factory=list)
    state: DialogueState = DialogueState.GREETING
    user_preference: UserPreference = field(default_factory=UserPreference)
    current_products: List[Product] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str, metadata: Dict[str, Any] = None):
        """添加消息"""
        self.messages.append(Message(
            role=role,
            content=content,
            metadata=metadata or {}
        ))
        self.updated_at = datetime.now()

    def get_recent_messages(self, n: int = 10) -> List[Dict[str, str]]:
        """获取最近的消息"""
        return [
            {"role": m.role, "content": m.content}
            for m in self.messages[-n:]
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "state": self.state.value,
            "user_preference": self.user_preference.to_dict(),
            "message_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


@dataclass
class ToolCall:
    """工具调用"""
    name: str
    arguments: Dict[str, Any]
    result: Any = None


@dataclass
class AssistantResponse:
    """助手响应"""
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    state: DialogueState = DialogueState.NEED_COLLECTING
    products: List[Product] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
