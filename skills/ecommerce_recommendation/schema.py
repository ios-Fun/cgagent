"""电商推荐Skill的数据模型定义"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class DialogueState(Enum):
    """对话状态枚举"""
    INITIAL = "initial"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    INFORMATION_GATHERING = "information_gathering"
    RECOMMENDATION_READY = "recommendation_ready"
    EXPLAINING_DETAILS = "explaining_details"
    CONFIRMATION_PENDING = "confirmation_pending"
    TASK_COMPLETED = "task_completed"


class UserIntent(Enum):
    """用户意图枚举"""
    PRODUCT_INQUIRY = "product_inquiry"  # 商品询问
    RECOMMENDATION_REQUEST = "recommendation_request"  # 推荐请求
    COMPARISON_REQUEST = "comparison_request"  # 对比请求
    DETAIL_INQUIRY = "detail_inquiry"  # 详情询问
    PURCHASE_INTENTION = "purchase_intention"  # 购买意向
    GENERAL_CHAT = "general_chat"  # 闲聊


@dataclass
class Constraint:
    """约束条件"""
    type: str  # price_range, brand, category, feature, etc.
    value: Any
    required: bool = True
    weight: float = 1.0


@dataclass
class DemandAnalysis:
    """需求分析结果"""
    intent: UserIntent
    category: Optional[str] = None
    constraints: List[Constraint] = field(default_factory=list)
    missing_info: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.value,
            "category": self.category,
            "constraints": [
                {
                    "type": c.type,
                    "value": c.value,
                    "required": c.required,
                    "weight": c.weight
                }
                for c in self.constraints
            ],
            "missing_info": self.missing_info
        }


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    preferred_brands: List[str] = field(default_factory=list)
    price_preference: Optional[str] = None  # low, medium, high
    recent_views: List[str] = field(default_factory=list)
    purchase_history: List[Dict[str, Any]] = field(default_factory=list)
    preference_tags: List[str] = field(default_factory=list)
    demographics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "preferred_brands": self.preferred_brands,
            "price_preference": self.price_preference,
            "recent_views": self.recent_views,
            "purchase_history": self.purchase_history,
            "preference_tags": self.preference_tags,
            "demographics": self.demographics
        }


@dataclass
class Product:
    """商品信息"""
    product_id: str
    name: str
    brand: str
    price: float
    category: str
    description: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    rating: float = 0.0
    sales: int = 0
    stock: int = 0
    image_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "brand": self.brand,
            "price": self.price,
            "category": self.category,
            "description": self.description,
            "attributes": self.attributes,
            "rating": self.rating,
            "sales": self.sales,
            "stock": self.stock,
            "image_url": self.image_url
        }


@dataclass
class RecommendationFactor:
    """推荐因素"""
    factor_name: str
    score: float
    reason: str


@dataclass
class RecommendedProduct:
    """推荐商品"""
    rank: int
    product: Product
    total_score: float
    match_factors: Dict[str, float]
    recommendation_reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "product": self.product.to_dict(),
            "total_score": self.total_score,
            "match_factors": self.match_factors,
            "recommendation_reasons": self.recommendation_reasons
        }


@dataclass
class RecommendationResult:
    """推荐结果"""
    query_id: str
    user_id: Optional[str]
    dialogue_state: DialogueState
    demand_analysis: DemandAnalysis
    user_profile: Optional[UserProfile]
    recommendations: List[RecommendedProduct]
    total_candidates: int
    response_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "user_id": self.user_id,
            "dialogue_state": self.dialogue_state.value,
            "demand_analysis": self.demand_analysis.to_dict(),
            "user_profile": self.user_profile.to_dict() if self.user_profile else None,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "total_candidates": self.total_candidates,
            "response_text": self.response_text,
            "metadata": self.metadata
        }


@dataclass
class ProductComparison:
    """商品对比结果"""
    products: List[Product]
    comparison_points: Dict[str, Dict[str, Any]]
    recommendation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "products": [p.to_dict() for p in self.products],
            "comparison_points": self.comparison_points,
            "recommendation": self.recommendation
        }
