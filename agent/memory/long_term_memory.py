"""
长期记忆门面（SQLite + deerflow 风格画像）

能力：
1. 对话开始加载用户画像并注入系统提示词
2. 对话后入队异步更新（LLM 抽取 + 规则兜底，防抖）
3. 保留扁平事实检索 API（兼容旧调用）
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    JSON,
    select,
    update,
    delete,
    and_,
    desc,
)
from sqlalchemy.sql import func

from app.gateway.database import Base
from agent.memory.config import get_memory_config
from agent.memory.message_processing import (
    detect_correction,
    detect_reinforcement,
    filter_messages_for_memory,
)
from agent.memory.prompt import format_memory_for_injection
from agent.memory.queue import get_memory_queue
from agent.memory.storage import get_memory_storage
from agent.memory.updater import (
    clear_memory_data,
    create_memory_fact,
    delete_memory_fact,
    get_memory_data,
    reload_memory_data,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LongTermMemoryType(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    BACKGROUND = "background"
    EVENT = "event"
    RELATIONSHIP = "relationship"


# ---------------------------------------------------------------------------
# 扁平事实表（补充检索；主画像在 user_memory_profiles）
# ---------------------------------------------------------------------------

class LongTermMemoryModel(Base):
    """扁平长期记忆事实（关键词检索用，与画像 facts 同步写入可选）"""

    __tablename__ = "long_term_memories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    content = Column(Text, nullable=False)
    memory_type = Column(String, nullable=False, default=LongTermMemoryType.FACT.value, index=True)
    importance = Column(Integer, nullable=False, default=3)
    keywords = Column(JSON, default=list)
    tags = Column(JSON, default=list)
    source_session_id = Column(String, nullable=True, index=True)
    content_hash = Column(String, nullable=False, index=True)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    meta_data = Column(JSON, default=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "content": self.content,
            "memory_type": self.memory_type,
            "importance": self.importance,
            "keywords": self.keywords or [],
            "tags": self.tags or [],
            "source_session_id": self.source_session_id,
            "access_count": self.access_count or 0,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "meta_data": self.meta_data or {},
        }


@dataclass
class MemoryItem:
    content: str
    memory_type: str = LongTermMemoryType.FACT.value
    importance: int = 3
    keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    source_session_id: Optional[str] = None
    meta_data: Dict[str, Any] = field(default_factory=dict)

    def content_hash(self, user_id: str) -> str:
        raw = f"{user_id}|{self.memory_type}|{self.content.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


_STOP_WORDS = {
    "的", "是", "在", "有", "我", "了", "和", "也", "就", "都", "而", "及", "与",
    "the", "is", "in", "and", "to", "a", "of", "for", "on", "with", "you", "me",
}

_PREFERENCE_PATTERNS = [
    (re.compile(r"(?:我喜欢|我偏好|我倾向|请用|希望你|以后请|记住我喜欢)\s*(.+)"), LongTermMemoryType.PREFERENCE, 4),
    (re.compile(r"(?:不要|别|禁止|不要用)\s*(.+)"), LongTermMemoryType.PREFERENCE, 4),
    (re.compile(r"(?:我的名字是|叫我|我叫)\s*(.+)"), LongTermMemoryType.BACKGROUND, 5),
    (re.compile(r"(?:我是|我在|我所在|我们单位|所属)\s*(.+)"), LongTermMemoryType.BACKGROUND, 4),
    (re.compile(r"(?:请记住|记住|记一下|长期记住)[:：]?\s*(.+)"), LongTermMemoryType.FACT, 5),
    (re.compile(r"(?:重要|关键事实|背景)[:：]\s*(.+)"), LongTermMemoryType.FACT, 4),
]


def extract_keywords(text: str, limit: int = 12) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]{2,}", text.lower())
    seen: Set[str] = set()
    out: List[str] = []
    for w in words:
        if w in _STOP_WORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= limit:
            break
    return out


def extract_memories_from_text(
    user_message: str,
    assistant_message: Optional[str] = None,
    session_id: Optional[str] = None,
) -> List[MemoryItem]:
    items: List[MemoryItem] = []
    text = (user_message or "").strip()
    if not text:
        return items

    for pattern, mtype, importance in _PREFERENCE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        snippet = m.group(0).strip()
        if len(snippet) < 4:
            continue
        items.append(
            MemoryItem(
                content=snippet[:500],
                memory_type=mtype.value,
                importance=importance,
                keywords=extract_keywords(snippet),
                tags=[mtype.value],
                source_session_id=session_id,
                meta_data={"source": "rule_extract"},
            )
        )

    if not items and re.search(r"(请记住|记住|记一下)", text):
        items.append(
            MemoryItem(
                content=text[:500],
                memory_type=LongTermMemoryType.FACT.value,
                importance=5,
                keywords=extract_keywords(text),
                tags=["fact", "explicit"],
                source_session_id=session_id,
                meta_data={"source": "explicit_remember"},
            )
        )

    uniq: Dict[str, MemoryItem] = {}
    for it in items:
        key = it.content.strip().lower()
        if key not in uniq or it.importance > uniq[key].importance:
            uniq[key] = it
    values = list(uniq.values())
    filtered: List[MemoryItem] = []
    for it in sorted(values, key=lambda x: (-x.importance, -len(x.content))):
        c = it.content.strip().lower()
        if any(c != other.content.strip().lower() and c in other.content.strip().lower() for other in filtered):
            continue
        filtered.append(it)
    return filtered


def format_memories_for_prompt(memories: List[Dict[str, Any]], max_items: int = 12) -> str:
    if not memories:
        return ""
    lines = ["# 用户长期记忆（个性化上下文）", "以下信息来自该用户的历史偏好与重要事实，请在回复中优先参考："]
    for i, m in enumerate(memories[:max_items], 1):
        mtype = m.get("memory_type") or m.get("category") or "fact"
        content = (m.get("content") or "").strip()
        if not content:
            continue
        imp = m.get("importance", m.get("confidence", 3))
        lines.append(f"{i}. [{mtype}|{imp}] {content}")
    lines.append("若记忆与当前问题无关可忽略；不要编造未列出的用户信息。")
    return "\n".join(lines)


class LongTermMemoryStore:
    """扁平事实 SQLite 访问（补充检索）。"""

    async def add_or_update(self, user_id: str, item: MemoryItem) -> Optional[str]:
        from app.gateway.database import _async_session_maker

        if _async_session_maker is None:
            return None
        ch = item.content_hash(user_id)
        async with _async_session_maker() as session:
            result = await session.execute(
                select(LongTermMemoryModel).where(
                    and_(
                        LongTermMemoryModel.user_id == user_id,
                        LongTermMemoryModel.content_hash == ch,
                    )
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.importance = max(existing.importance or 0, item.importance)
                existing.access_count = (existing.access_count or 0) + 1
                now = _utcnow()
                existing.last_accessed = now
                existing.updated_at = now
                if item.keywords:
                    merged = list(dict.fromkeys((existing.keywords or []) + item.keywords))
                    existing.keywords = merged[:20]
                await session.commit()
                return existing.id

            row = LongTermMemoryModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                content=item.content,
                memory_type=item.memory_type,
                importance=item.importance,
                keywords=item.keywords,
                tags=item.tags,
                source_session_id=item.source_session_id,
                content_hash=ch,
                access_count=0,
                meta_data=item.meta_data or {},
            )
            session.add(row)
            await session.commit()
            return row.id

    async def search(
        self,
        user_id: str,
        query: Optional[str] = None,
        limit: int = 10,
        memory_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        from app.gateway.database import _async_session_maker

        if _async_session_maker is None:
            return []
        async with _async_session_maker() as session:
            stmt = select(LongTermMemoryModel).where(LongTermMemoryModel.user_id == user_id)
            if memory_types:
                stmt = stmt.where(LongTermMemoryModel.memory_type.in_(memory_types))
            if not query or not query.strip():
                stmt = stmt.order_by(
                    desc(LongTermMemoryModel.importance),
                    desc(LongTermMemoryModel.last_accessed),
                ).limit(limit)
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
            else:
                stmt = stmt.order_by(desc(LongTermMemoryModel.importance)).limit(200)
                result = await session.execute(stmt)
                candidates = list(result.scalars().all())
                q_keywords = set(extract_keywords(query, limit=20))
                scored = []
                for row in candidates:
                    score = float(row.importance or 0)
                    content_l = (row.content or "").lower()
                    kws = set((row.keywords or []) + extract_keywords(row.content or "", 15))
                    overlap = len(q_keywords & kws)
                    for kw in q_keywords:
                        if kw in content_l:
                            overlap += 1
                    score += overlap * 2.0
                    if overlap > 0 or not q_keywords:
                        scored.append((score, row))
                if not scored:
                    scored = [(float(r.importance or 0), r) for r in candidates[:limit]]
                scored.sort(key=lambda x: x[0], reverse=True)
                rows = [r for _, r in scored[:limit]]

            payloads = [r.to_dict() for r in rows]
            ids = [p["id"] for p in payloads if p.get("id")]
            if ids:
                await session.execute(
                    update(LongTermMemoryModel)
                    .where(LongTermMemoryModel.id.in_(ids))
                    .values(
                        access_count=LongTermMemoryModel.access_count + 1,
                        last_accessed=func.now(),
                    )
                )
                await session.commit()
            return payloads

    async def list_by_user(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return await self.search(user_id=user_id, query=None, limit=limit)

    async def delete(self, user_id: str, memory_id: str) -> bool:
        from app.gateway.database import _async_session_maker

        if _async_session_maker is None:
            return False
        async with _async_session_maker() as session:
            result = await session.execute(
                delete(LongTermMemoryModel).where(
                    and_(
                        LongTermMemoryModel.id == memory_id,
                        LongTermMemoryModel.user_id == user_id,
                    )
                )
            )
            await session.commit()
            return (result.rowcount or 0) > 0


class LongTermMemoryService:
    """
    主门面：
    - load profile + format injection（deerflow）
    - enqueue conversation for LLM update（debounce queue）
    - 兼容扁平事实检索
    """

    def __init__(self, store: Optional[LongTermMemoryStore] = None):
        self.store = store or LongTermMemoryStore()
        self._started = False

    async def start(self):
        self._started = True
        logger.info("LongTermMemoryService started (SQLite profile + debounce queue)")

    async def stop(self):
        try:
            get_memory_queue().flush()
        except Exception:
            pass
        self._started = False
        logger.info("LongTermMemoryService stopped")

    def get_profile(self, user_id: str, agent_name: Optional[str] = None) -> Dict[str, Any]:
        if not user_id:
            return {}
        return get_memory_data(agent_name, user_id=user_id)

    def build_injection_from_profile(
        self,
        user_id: str,
        agent_name: Optional[str] = None,
    ) -> str:
        config = get_memory_config()
        if not config.enabled or not config.injection_enabled or not user_id:
            return ""
        memory_data = get_memory_data(agent_name, user_id=user_id)
        return format_memory_for_injection(
            memory_data,
            max_tokens=config.max_injection_tokens,
            guaranteed_categories=config.guaranteed_categories,
            guaranteed_token_budget=config.guaranteed_token_budget,
        )

    async def retrieve_for_conversation(
        self,
        user_id: str,
        user_message: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """兼容旧接口：优先画像 facts，再扁平表。"""
        if not user_id:
            return []
        profile = get_memory_data(user_id=user_id)
        facts = profile.get("facts") or []
        out: List[Dict[str, Any]] = []
        q_kw = set(extract_keywords(user_message or "", 15))
        for f in facts:
            if not isinstance(f, dict):
                continue
            content = f.get("content") or ""
            score = float(f.get("confidence") or 0)
            if q_kw:
                c_l = content.lower()
                for kw in q_kw:
                    if kw in c_l:
                        score += 1
            out.append(
                {
                    "id": f.get("id"),
                    "content": content,
                    "memory_type": f.get("category", "fact"),
                    "importance": f.get("confidence", 0.5),
                    "category": f.get("category"),
                    "confidence": f.get("confidence"),
                    "_score": score,
                }
            )
        out.sort(key=lambda x: x.get("_score", 0), reverse=True)
        if out:
            return out[:limit]
        try:
            return await self.store.search(user_id=user_id, query=user_message, limit=limit)
        except Exception as e:
            logger.exception("retrieve flat memory failed: %s", e)
            return []

    def build_system_memory_block(self, memories: List[Dict[str, Any]]) -> str:
        """旧接口：列表注入。新路径优先用 build_injection_from_profile。"""
        return format_memories_for_prompt(memories)

    def enqueue_conversation(
        self,
        user_id: str,
        messages: List[Any],
        session_id: str,
        agent_name: Optional[str] = None,
        immediate: bool = False,
    ) -> None:
        """将对话入队异步更新画像（不阻塞主流程）。"""
        config = get_memory_config()
        if not config.enabled or not user_id:
            return
        filtered = filter_messages_for_memory(messages)
        if not filtered:
            return
        correction = detect_correction(filtered)
        reinforcement = (not correction) and detect_reinforcement(filtered)
        queue = get_memory_queue()
        if immediate or correction:
            queue.add_nowait(
                thread_id=session_id,
                messages=filtered,
                agent_name=agent_name,
                user_id=user_id,
                correction_detected=correction,
                reinforcement_detected=reinforcement,
            )
        else:
            queue.add(
                thread_id=session_id,
                messages=filtered,
                agent_name=agent_name,
                user_id=user_id,
                correction_detected=correction,
                reinforcement_detected=reinforcement,
            )

    def enqueue_from_turn(
        self,
        user_id: str,
        user_message: str,
        assistant_message: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """兼容：单轮对话入队。"""
        if not user_id or not user_message:
            return
        messages = [
            {"role": "user", "content": user_message},
        ]
        if assistant_message:
            messages.append({"role": "assistant", "content": assistant_message})
        self.enqueue_conversation(
            user_id=user_id,
            messages=messages,
            session_id=session_id or f"sess_{uuid.uuid4().hex[:12]}",
        )

    async def save_explicit(
        self,
        user_id: str,
        content: str,
        memory_type: str = LongTermMemoryType.FACT.value,
        importance: int = 4,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        cat_map = {
            "preference": "preference",
            "background": "context",
            "fact": "context",
            "event": "context",
            "relationship": "context",
        }
        conf = min(1.0, 0.5 + importance * 0.1)
        try:
            create_memory_fact(
                content=content,
                category=cat_map.get(memory_type, "context"),
                confidence=conf,
                user_id=user_id,
            )
        except Exception as e:
            logger.exception("save profile fact failed: %s", e)

        item = MemoryItem(
            content=content,
            memory_type=memory_type,
            importance=importance,
            keywords=extract_keywords(content),
            tags=[memory_type],
            source_session_id=session_id,
            meta_data={"source": "explicit_api"},
        )
        return await self.store.add_or_update(user_id, item)


_ltm_service: Optional[LongTermMemoryService] = None


def get_long_term_memory_service() -> LongTermMemoryService:
    global _ltm_service
    if _ltm_service is None:
        _ltm_service = LongTermMemoryService()
    return _ltm_service
