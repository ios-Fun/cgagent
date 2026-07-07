"""
用户画像系统

跨会话偏好学习、用户行为模式分析和画像持久化
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Callable
from datetime import datetime
from collections import defaultdict
import hashlib


@dataclass
class Preference:
    """用户偏好项"""
    key: str
    value: Any
    confidence: float = 1.0  # 0-1，偏好的置信度
    source: str = "explicit"  # explicit(明确表达), implicit(隐式推断), inferred(推断)
    timestamp: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)

    def is_fresh(self, max_age: int = 86400 * 30) -> bool:
        """检查偏好是否新鲜（默认30天）"""
        return (time.time() - self.timestamp) < max_age


@dataclass
class BehaviorPattern:
    """用户行为模式"""
    pattern_id: str
    pattern_type: str  # temporal(时间), sequential(顺序), frequency(频率)
    description: str
    confidence: float = 0.0
    occurrence_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)

    def update_occurrence(self):
        """更新出现次数"""
        self.occurrence_count += 1
        self.last_seen = time.time()


@dataclass
class InteractionStats:
    """交互统计"""
    total_sessions: int = 0
    total_messages: int = 0
    total_user_messages: int = 0
    total_assistant_messages: int = 0
    average_session_duration: float = 0.0
    first_interaction: Optional[float] = None
    last_interaction: Optional[float] = None

    # 响应时间统计
    response_times: List[float] = field(default_factory=list)

    # 满意度（如果有反馈）
    satisfaction_ratings: List[int] = field(default_factory=list)

    def record_message(self, role: str):
        """记录消息"""
        self.total_messages += 1
        if role == "user":
            self.total_user_messages += 1
        elif role == "assistant":
            self.total_assistant_messages += 1

    def record_response_time(self, duration: float):
        """记录响应时间"""
        self.response_times.append(duration)
        # 只保留最近100个
        if len(self.response_times) > 100:
            self.response_times = self.response_times[-100:]

    def get_average_response_time(self) -> float:
        """获取平均响应时间"""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)

    def record_satisfaction(self, rating: int):
        """记录满意度评分"""
        self.satisfaction_ratings.append(rating)

    def get_average_satisfaction(self) -> float:
        """获取平均满意度"""
        if not self.satisfaction_ratings:
            return 0.0
        return sum(self.satisfaction_ratings) / len(self.satisfaction_ratings)


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # 基本信息
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    # 偏好
    preferences: Dict[str, Preference] = field(default_factory=dict)

    # 行为模式
    behavior_patterns: Dict[str, BehaviorPattern] = field(default_factory=dict)

    # 交互统计
    stats: InteractionStats = field(default_factory=InteractionStats)

    # 标签
    tags: Set[str] = field(default_factory=set)

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_timestamp(self):
        """更新修改时间"""
        self.updated_at = time.time()

    def set_preference(self, key: str, value: Any, confidence: float = 1.0,
                       source: str = "explicit", context: Optional[Dict] = None):
        """设置用户偏好"""
        self.preferences[key] = Preference(
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            context=context or {}
        )
        self.update_timestamp()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """获取用户偏好"""
        pref = self.preferences.get(key)
        return pref.value if pref else default

    def has_preference(self, key: str) -> bool:
        """检查是否存在偏好"""
        return key in self.preferences

    def add_behavior_pattern(self, pattern: BehaviorPattern):
        """添加行为模式"""
        self.behavior_patterns[pattern.pattern_id] = pattern
        self.update_timestamp()

    def get_behavior_pattern(self, pattern_id: str) -> Optional[BehaviorPattern]:
        """获取行为模式"""
        return self.behavior_patterns.get(pattern_id)

    def record_session_start(self):
        """记录会话开始"""
        self.stats.total_sessions += 1
        if self.stats.first_interaction is None:
            self.stats.first_interaction = time.time()
        self.stats.last_interaction = time.time()
        self.update_timestamp()

    def record_message(self, role: str):
        """记录消息"""
        self.stats.record_message(role)
        self.stats.last_interaction = time.time()

    def add_tag(self, tag: str):
        """添加标签"""
        self.tags.add(tag)
        self.update_timestamp()

    def remove_tag(self, tag: str):
        """移除标签"""
        self.tags.discard(tag)
        self.update_timestamp()

    def has_tag(self, tag: str) -> bool:
        """检查标签"""
        return tag in self.tags

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "display_name": self.display_name,
            "email": self.email,
            "phone": self.phone,
            "preferences": {
                k: {
                    "key": v.key,
                    "value": v.value,
                    "confidence": v.confidence,
                    "source": v.source,
                    "timestamp": v.timestamp,
                    "context": v.context
                } for k, v in self.preferences.items()
            },
            "behavior_patterns": {
                k: asdict(v) for k, v in self.behavior_patterns.items()
            },
            "stats": asdict(self.stats),
            "tags": list(self.tags),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """从字典创建"""
        profile = cls(
            user_id=data["user_id"],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            display_name=data.get("display_name"),
            email=data.get("email"),
            phone=data.get("phone")
        )

        # 恢复偏好
        for k, v in data.get("preferences", {}).items():
            profile.preferences[k] = Preference(
                key=v["key"],
                value=v["value"],
                confidence=v.get("confidence", 1.0),
                source=v.get("source", "explicit"),
                timestamp=v.get("timestamp", time.time()),
                context=v.get("context", {})
            )

        # 恢复行为模式
        for k, v in data.get("behavior_patterns", {}).items():
            profile.behavior_patterns[k] = BehaviorPattern(**v)

        # 恢复统计
        stats_data = data.get("stats", {})
        profile.stats = InteractionStats(**stats_data)

        # 恢复标签
        profile.tags = set(data.get("tags", []))

        # 恢复元数据
        profile.metadata = data.get("metadata", {})

        return profile


class UserProfileManager:
    """
    用户画像管理器

    管理用户画像的加载、保存和查询
    """

    def __init__(self, storage_backend: Optional[Any] = None):
        self.storage = storage_backend
        self._profiles: Dict[str, UserProfile] = {}
        self._cache_enabled = True

    def get_profile(self, user_id: str, create_if_missing: bool = True) -> Optional[UserProfile]:
        """获取用户画像"""
        # 从缓存获取
        if user_id in self._profiles:
            return self._profiles[user_id]

        # 从存储加载
        if self.storage:
            profile_data = self._load_from_storage(user_id)
            if profile_data:
                profile = UserProfile.from_dict(profile_data)
                if self._cache_enabled:
                    self._profiles[user_id] = profile
                return profile

        # 创建新画像
        if create_if_missing:
            profile = UserProfile(user_id=user_id)
            if self._cache_enabled:
                self._profiles[user_id] = profile
            return profile

        return None

    def save_profile(self, profile: UserProfile):
        """保存用户画像"""
        profile.update_timestamp()

        # 更新缓存
        if self._cache_enabled:
            self._profiles[profile.user_id] = profile

        # 保存到存储
        if self.storage:
            self._save_to_storage(profile.user_id, profile.to_dict())

    def delete_profile(self, user_id: str):
        """删除用户画像"""
        # 从缓存删除
        self._profiles.pop(user_id, None)

        # 从存储删除
        if self.storage:
            self._delete_from_storage(user_id)

    def find_profiles_by_tag(self, tag: str) -> List[UserProfile]:
        """根据标签查找用户画像"""
        results = []
        for profile in self._profiles.values():
            if profile.has_tag(tag):
                results.append(profile)
        return results

    def find_profiles_by_preference(self, key: str, value: Any) -> List[UserProfile]:
        """根据偏好查找用户画像"""
        results = []
        for profile in self._profiles.values():
            if profile.get_preference(key) == value:
                results.append(profile)
        return results

    def get_all_profiles(self) -> List[UserProfile]:
        """获取所有用户画像"""
        return list(self._profiles.values())

    def clear_cache(self):
        """清空缓存"""
        self._profiles.clear()

    def _load_from_storage(self, user_id: str) -> Optional[Dict[str, Any]]:
        """从存储加载"""
        if hasattr(self.storage, 'get'):
            return self.storage.get(f"user_profile:{user_id}")
        return None

    def _save_to_storage(self, user_id: str, data: Dict[str, Any]):
        """保存到存储"""
        if hasattr(self.storage, 'set'):
            self.storage.set(f"user_profile:{user_id}", data)

    def _delete_from_storage(self, user_id: str):
        """从存储删除"""
        if hasattr(self.storage, 'delete'):
            self.storage.delete(f"user_profile:{user_id}")


# 便捷函数
def create_user_profile_manager(storage_backend: Optional[Any] = None) -> UserProfileManager:
    """创建用户画像管理器"""
    return UserProfileManager(storage_backend)