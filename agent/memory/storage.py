"""记忆存储：SQLite 持久化 deerflow 风格画像。"""

from __future__ import annotations

import abc
import asyncio
import copy
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Column, DateTime, JSON, String, select
from sqlalchemy.sql import func

from app.gateway.database import Base

logger = logging.getLogger(__name__)


def utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().removesuffix("+00:00") + "Z"


def create_empty_memory() -> Dict[str, Any]:
    return {
        "version": "1.0",
        "lastUpdated": utc_now_iso_z(),
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": [],
    }


class UserMemoryProfileModel(Base):
    """每用户一份完整记忆画像（JSON）。"""

    __tablename__ = "user_memory_profiles"

    user_id = Column(String, primary_key=True)
    agent_name = Column(String, primary_key=True, default="")
    memory_data = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MemoryStorage(abc.ABC):
    @abc.abstractmethod
    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    def save(
        self,
        memory_data: Dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
    ) -> bool:
        pass


class SqliteMemoryStorage(MemoryStorage):
    """基于 SQLite（aiosqlite）的记忆存储，带内存缓存。"""

    def __init__(self):
        self._cache: Dict[tuple[str | None, str | None], Dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(agent_name: str | None, user_id: str | None) -> tuple[str | None, str | None]:
        return (user_id, agent_name or "")

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
        if not user_id:
            return create_empty_memory()
        key = self._key(agent_name, user_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return copy.deepcopy(cached)

        data = self._run_sync(self._aload(user_id, agent_name or ""))
        with self._lock:
            self._cache[key] = copy.deepcopy(data)
        return copy.deepcopy(data)

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
        if not user_id:
            return create_empty_memory()
        data = self._run_sync(self._aload(user_id, agent_name or ""))
        key = self._key(agent_name, user_id)
        with self._lock:
            self._cache[key] = copy.deepcopy(data)
        return copy.deepcopy(data)

    def save(
        self,
        memory_data: Dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
    ) -> bool:
        if not user_id:
            logger.warning("save memory skipped: missing user_id")
            return False
        payload = {**memory_data, "lastUpdated": utc_now_iso_z()}
        ok = self._run_sync(self._asave(user_id, agent_name or "", payload))
        if ok:
            with self._lock:
                self._cache[self._key(agent_name, user_id)] = copy.deepcopy(payload)
        return ok

    async def aload(self, agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
        if not user_id:
            return create_empty_memory()
        data = await self._aload(user_id, agent_name or "")
        with self._lock:
            self._cache[self._key(agent_name, user_id)] = copy.deepcopy(data)
        return copy.deepcopy(data)

    async def asave(
        self,
        memory_data: Dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
    ) -> bool:
        if not user_id:
            return False
        payload = {**memory_data, "lastUpdated": utc_now_iso_z()}
        ok = await self._asave(user_id, agent_name or "", payload)
        if ok:
            with self._lock:
                self._cache[self._key(agent_name, user_id)] = copy.deepcopy(payload)
        return ok

    async def _aload(self, user_id: str, agent_name: str) -> Dict[str, Any]:
        from app.gateway.database import _async_session_maker

        if _async_session_maker is None:
            return create_empty_memory()
        try:
            async with _async_session_maker() as session:
                result = await session.execute(
                    select(UserMemoryProfileModel).where(
                        UserMemoryProfileModel.user_id == user_id,
                        UserMemoryProfileModel.agent_name == agent_name,
                    )
                )
                row = result.scalar_one_or_none()
                if not row or not row.memory_data:
                    return create_empty_memory()
                data = row.memory_data
                if not isinstance(data, dict):
                    return create_empty_memory()
                # 保证结构完整
                empty = create_empty_memory()
                empty.update({k: data.get(k, empty[k]) for k in empty})
                empty["user"] = {**empty["user"], **(data.get("user") or {})}
                empty["history"] = {**empty["history"], **(data.get("history") or {})}
                empty["facts"] = data.get("facts") or []
                empty["version"] = data.get("version", "1.0")
                empty["lastUpdated"] = data.get("lastUpdated") or empty["lastUpdated"]
                return empty
        except Exception as e:
            logger.exception("load memory failed: %s", e)
            return create_empty_memory()

    async def _asave(self, user_id: str, agent_name: str, memory_data: Dict[str, Any]) -> bool:
        from app.gateway.database import _async_session_maker

        if _async_session_maker is None:
            logger.warning("database not initialized")
            return False
        try:
            async with _async_session_maker() as session:
                result = await session.execute(
                    select(UserMemoryProfileModel).where(
                        UserMemoryProfileModel.user_id == user_id,
                        UserMemoryProfileModel.agent_name == agent_name,
                    )
                )
                row = result.scalar_one_or_none()
                if row:
                    row.memory_data = memory_data
                else:
                    session.add(
                        UserMemoryProfileModel(
                            user_id=user_id,
                            agent_name=agent_name,
                            memory_data=memory_data,
                        )
                    )
                await session.commit()
                return True
        except Exception as e:
            logger.exception("save memory failed: %s", e)
            return False

    @staticmethod
    def _run_sync(coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        # 已有事件循环：放到线程里跑新 loop，避免嵌套
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(coro)).result(timeout=30)


_storage_instance: Optional[SqliteMemoryStorage] = None
_storage_lock = threading.Lock()


def get_memory_storage() -> SqliteMemoryStorage:
    global _storage_instance
    with _storage_lock:
        if _storage_instance is None:
            _storage_instance = SqliteMemoryStorage()
        return _storage_instance
