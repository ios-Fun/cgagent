"""
记忆管理器

提供记忆压缩、语义检索和遗忘机制
"""

import time
import json
import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Tuple, Set
from enum import Enum
import re


class MemoryType(Enum):
    """记忆类型"""
    FACT = "fact"               # 事实
    PREFERENCE = "preference"   # 偏好
    EVENT = "event"             # 事件
    CONCEPT = "concept"         # 概念
    PROCEDURE = "procedure"     # 程序/步骤
    RELATIONSHIP = "relationship"  # 关系


class MemoryImportance(Enum):
    """记忆重要性级别"""
    CRITICAL = 5    # 关键信息，永不忘却
    HIGH = 4        # 重要信息，长期保留
    MEDIUM = 3      # 一般信息，中期保留
    LOW = 2         # 次要信息，短期保留
    TRIVIAL = 1     # 琐碎信息，快速遗忘


@dataclass
class MemoryEntry:
    """记忆条目"""
    memory_id: str
    content: str
    memory_type: MemoryType = MemoryType.FACT
    importance: MemoryImportance = MemoryImportance.MEDIUM

    # 时间戳
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0

    # 语义相关
    embedding: Optional[List[float]] = None
    keywords: List[str] = field(default_factory=list)
    tags: Set[str] = field(default_factory=set)

    # 上下文
    context: Dict[str, Any] = field(default_factory=dict)
    related_memories: List[str] = field(default_factory=list)

    # 遗忘机制
    decay_factor: float = 1.0  # 衰减因子
    retention_score: float = 1.0  # 保留分数 (0-1)

    def access(self):
        """访问记忆，更新访问统计"""
        self.last_accessed = time.time()
        self.access_count += 1

    def update_retention_score(self, current_time: Optional[float] = None):
        """更新保留分数（基于遗忘曲线）"""
        current_time = current_time or time.time()
        time_since_creation = current_time - self.created_at
        time_since_access = current_time - self.last_accessed

        # 基础保留分数基于重要性
        base_score = self.importance.value / 5.0

        # 访问频率加成
        access_bonus = min(self.access_count * 0.05, 0.3)

        # 时间衰减 (指数衰减)
        decay_rate = 0.1 * (6 - self.importance.value)  # 重要性越低，衰减越快
        time_decay = math.exp(-decay_rate * time_since_access / 86400)  # 按天衰减

        # 计算最终保留分数
        self.retention_score = min(1.0, (base_score + access_bonus) * time_decay)

        return self.retention_score

    def should_forget(self, threshold: float = 0.1) -> bool:
        """检查是否应该遗忘"""
        return self.retention_score < threshold

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "memory_type": self.memory_type.value,
            "importance": self.importance.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "embedding": self.embedding,
            "keywords": self.keywords,
            "tags": list(self.tags),
            "context": self.context,
            "related_memories": self.related_memories,
            "retention_score": self.retention_score
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        """从字典创建"""
        return cls(
            memory_id=data["memory_id"],
            content=data["content"],
            memory_type=MemoryType(data.get("memory_type", "fact")),
            importance=MemoryImportance(data.get("importance", 3)),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            last_accessed=data.get("last_accessed", time.time()),
            access_count=data.get("access_count", 0),
            embedding=data.get("embedding"),
            keywords=data.get("keywords", []),
            tags=set(data.get("tags", [])),
            context=data.get("context", {}),
            related_memories=data.get("related_memories", []),
            retention_score=data.get("retention_score", 1.0)
        )


import math


class MemoryManager:
    """
    记忆管理器

    提供记忆存储、压缩、检索和遗忘机制
    """

    def __init__(self, llm_client=None, vector_store=None, config: Optional[Dict[str, Any]] = None):
        self.llm_client = llm_client
        self.vector_store = vector_store
        self.config = config or {}

        # 配置
        self.max_memories = self.config.get("max_memories", 10000)
        self.compression_threshold = self.config.get("compression_threshold", 0.8)
        self.forget_threshold = self.config.get("forget_threshold", 0.1)
        self.retention_check_interval = self.config.get("retention_check_interval", 86400)

        # 记忆存储
        self._memories: Dict[str, MemoryEntry] = {}
        self._index_by_type: Dict[MemoryType, Set[str]] = defaultdict(set)
        self._index_by_tag: Dict[str, Set[str]] = defaultdict(set)
        self._index_by_keyword: Dict[str, Set[str]] = defaultdict(set)

        # 最后保留检查时间
        self._last_retention_check = time.time()

    def add_memory(self, content: str, memory_type: MemoryType = MemoryType.FACT,
                   importance: MemoryImportance = MemoryImportance.MEDIUM,
                   tags: Optional[Set[str]] = None,
                   context: Optional[Dict[str, Any]] = None,
                   embedding: Optional[List[float]] = None) -> MemoryEntry:
        """
        添加记忆

        Args:
            content: 记忆内容
            memory_type: 记忆类型
            importance: 重要性级别
            tags: 标签集合
            context: 上下文信息
            embedding: 向量嵌入

        Returns:
            MemoryEntry: 创建的记忆条目
        """
        # 生成记忆ID
        memory_id = self._generate_memory_id(content)

        # 提取关键词
        keywords = self._extract_keywords(content)

        # 生成嵌入向量（如果没有提供）
        if embedding is None and self.llm_client and hasattr(self.llm_client, 'embed'):
            try:
                embedding = self.llm_client.embed(content)
            except Exception:
                pass

        # 创建记忆条目
        entry = MemoryEntry(
            memory_id=memory_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            keywords=keywords,
            tags=tags or set(),
            context=context or {},
            embedding=embedding
        )

        # 存储记忆
        self._store_memory(entry)

        # 检查是否需要压缩
        if len(self._memories) > self.max_memories:
            self._compress_memories()

        return entry

    def get_memory(self, memory_id: str) -> Optional[MemoryEntry]:
        """获取记忆"""
        entry = self._memories.get(memory_id)
        if entry:
            entry.access()
        return entry

    def update_memory(self, memory_id: str, **updates) -> Optional[MemoryEntry]:
        """更新记忆"""
        entry = self._memories.get(memory_id)
        if not entry:
            return None

        for key, value in updates.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        entry.updated_at = time.time()
        entry.access()

        return entry

    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        entry = self._memories.pop(memory_id, None)
        if entry:
            # 清理索引
            self._index_by_type[entry.memory_type].discard(memory_id)
            for tag in entry.tags:
                self._index_by_tag[tag].discard(memory_id)
            for keyword in entry.keywords:
                self._index_by_keyword[keyword].discard(memory_id)
            return True
        return False

    def search_by_keywords(self, keywords: List[str]) -> List[MemoryEntry]:
        """通过关键词搜索"""
        memory_ids: Set[str] = set()
        for keyword in keywords:
            memory_ids.update(self._index_by_keyword.get(keyword.lower(), set()))

        results = []
        for mid in memory_ids:
            entry = self._memories.get(mid)
            if entry:
                entry.access()
                results.append(entry)

        # 按相关性和重要性排序
        results.sort(key=lambda e: (e.importance.value, e.access_count), reverse=True)
        return results

    def search_by_tags(self, tags: Set[str]) -> List[MemoryEntry]:
        """通过标签搜索"""
        memory_ids: Set[str] = set()
        for tag in tags:
            memory_ids.update(self._index_by_tag.get(tag, set()))

        results = []
        for mid in memory_ids:
            entry = self._memories.get(mid)
            if entry:
                entry.access()
                results.append(entry)

        return results

    def semantic_search(self, query: str, top_k: int = 5) -> List[Tuple[MemoryEntry, float]]:
        """语义搜索（需要向量存储）"""
        if not self.vector_store or not self.llm_client:
            return []

        try:
            # 生成查询向量
            query_embedding = self.llm_client.embed(query)

            # 在向量存储中搜索
            results = self.vector_store.search(query_embedding, top_k=top_k)

            # 转换为MemoryEntry
            entries = []
            for memory_id, score in results:
                entry = self._memories.get(memory_id)
                if entry:
                    entry.access()
                    entries.append((entry, score))

            return entries
        except Exception:
            return []

    def compress_memories(self, target_ratio: float = 0.5):
        """压缩记忆"""
        self._compress_memories(target_ratio)

    def forget_old_memories(self, max_age: int = 86400 * 30):
        """遗忘旧记忆"""
        current_time = time.time()
        to_forget = []

        for memory_id, entry in self._memories.items():
            # 检查保留分数
            entry.update_retention_score(current_time)

            # 如果保留分数低于阈值或超过最大年龄，则遗忘
            if entry.should_forget(self.forget_threshold):
                to_forget.append(memory_id)
            elif (current_time - entry.created_at) > max_age and entry.importance.value < 3:
                to_forget.append(memory_id)

        # 执行遗忘
        for memory_id in to_forget:
            self.delete_memory(memory_id)

        return len(to_forget)

    def _generate_memory_id(self, content: str) -> str:
        """生成记忆ID"""
        hash_input = f"{content}_{time.time()}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:16]

    def _extract_keywords(self, content: str) -> List[str]:
        """提取关键词"""
        # 简单的关键词提取：分词并过滤
        # 在实际应用中可以使用更复杂的NLP技术
        words = re.findall(r'\b[a-zA-Z0-9\u4e00-\u9fff]+\b', content.lower())

        # 过滤停用词（简化版）
        stop_words = {'的', '是', '在', '有', '我', '了', '和', 'the', 'is', 'in', 'and', 'to'}
        keywords = [w for w in words if w not in stop_words and len(w) > 1]

        # 去重并限制数量
        return list(set(keywords))[:10]

    def _store_memory(self, entry: MemoryEntry):
        """存储记忆到索引"""
        self._memories[entry.memory_id] = entry

        # 更新索引
        self._index_by_type[entry.memory_type].add(entry.memory_id)
        for tag in entry.tags:
            self._index_by_tag[tag].add(entry.memory_id)
        for keyword in entry.keywords:
            self._index_by_keyword[keyword.lower()].add(entry.memory_id)

        # 存储到向量存储
        if self.vector_store and entry.embedding:
            try:
                self.vector_store.store(entry.memory_id, entry.embedding, {
                    "content": entry.content,
                    "type": entry.memory_type.value,
                    "importance": entry.importance.value
                })
            except Exception:
                pass

    def _compress_memories(self, target_ratio: float = 0.5):
        """压缩记忆"""
        if len(self._memories) < 100:
            return

        # 计算目标数量
        target_count = int(len(self._memories) * target_ratio)
        to_remove = len(self._memories) - target_count

        if to_remove <= 0:
            return

        # 按重要性和访问频率排序
        memories_with_score = []
        for entry in self._memories.values():
            # 计算保留分数
            score = (
                entry.importance.value * 10 +
                entry.access_count * 2 +
                (1 if (time.time() - entry.last_accessed) < 86400 else 0)
            )
            memories_with_score.append((entry, score))

        # 按分数排序，删除低分的
        memories_with_score.sort(key=lambda x: x[1])

        for i in range(min(to_remove, len(memories_with_score))):
            entry = memories_with_score[i][0]
            self.delete_memory(entry.memory_id)


# 便捷函数
def create_memory_manager(llm_client=None, vector_store=None,
                          config: Optional[Dict[str, Any]] = None) -> MemoryManager:
    """创建记忆管理器"""
    return MemoryManager(llm_client, vector_store, config)