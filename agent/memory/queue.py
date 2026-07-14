"""记忆更新队列（防抖，对齐 deerflow）。"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional

from agent.memory.config import get_memory_config

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    thread_id: str
    messages: List[Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_name: Optional[str] = None
    user_id: Optional[str] = None
    correction_detected: bool = False
    reinforcement_detected: bool = False


class MemoryUpdateQueue:
    def __init__(self):
        self._queue: List[ConversationContext] = []
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._processing = False

    @staticmethod
    def _queue_key(thread_id: str, user_id: Optional[str], agent_name: Optional[str]):
        return (thread_id, user_id, agent_name)

    def add(
        self,
        thread_id: str,
        messages: List[Any],
        agent_name: Optional[str] = None,
        user_id: Optional[str] = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> None:
        config = get_memory_config()
        if not config.enabled:
            return
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
            self._schedule_timer(config.debounce_seconds)
        logger.info("Memory update queued thread=%s size=%d", thread_id, len(self._queue))

    def add_nowait(
        self,
        thread_id: str,
        messages: List[Any],
        agent_name: Optional[str] = None,
        user_id: Optional[str] = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
    ) -> None:
        config = get_memory_config()
        if not config.enabled:
            return
        with self._lock:
            self._enqueue_locked(
                thread_id=thread_id,
                messages=messages,
                agent_name=agent_name,
                user_id=user_id,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
            )
            self._schedule_timer(0)
        logger.info("Memory update immediate thread=%s size=%d", thread_id, len(self._queue))

    def _enqueue_locked(
        self,
        *,
        thread_id: str,
        messages: List[Any],
        agent_name: Optional[str],
        user_id: Optional[str],
        correction_detected: bool,
        reinforcement_detected: bool,
    ) -> None:
        key = self._queue_key(thread_id, user_id, agent_name)
        existing = next(
            (c for c in self._queue if self._queue_key(c.thread_id, c.user_id, c.agent_name) == key),
            None,
        )
        context = ConversationContext(
            thread_id=thread_id,
            messages=messages,
            agent_name=agent_name,
            user_id=user_id,
            correction_detected=correction_detected or (existing.correction_detected if existing else False),
            reinforcement_detected=reinforcement_detected or (existing.reinforcement_detected if existing else False),
        )
        self._queue = [c for c in self._queue if self._queue_key(c.thread_id, c.user_id, c.agent_name) != key]
        self._queue.append(context)

    def _schedule_timer(self, delay_seconds: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(delay_seconds, self._process_queue)
        self._timer.daemon = True
        self._timer.start()

    def _process_queue(self) -> None:
        from agent.memory.updater import MemoryUpdater

        with self._lock:
            if self._processing:
                self._schedule_timer(0)
                return
            if not self._queue:
                return
            self._processing = True
            contexts = self._queue.copy()
            self._queue.clear()
            self._timer = None

        logger.info("Processing %d memory updates", len(contexts))
        try:
            updater = MemoryUpdater()
            for ctx in contexts:
                try:
                    ok = updater.update_memory(
                        messages=ctx.messages,
                        thread_id=ctx.thread_id,
                        agent_name=ctx.agent_name,
                        correction_detected=ctx.correction_detected,
                        reinforcement_detected=ctx.reinforcement_detected,
                        user_id=ctx.user_id,
                    )
                    if ok:
                        logger.info("Memory updated thread=%s", ctx.thread_id)
                    else:
                        logger.warning("Memory update skipped thread=%s", ctx.thread_id)
                except Exception as e:
                    logger.error("Memory update error thread=%s: %s", ctx.thread_id, e)
                if len(contexts) > 1:
                    time.sleep(0.3)
        finally:
            with self._lock:
                self._processing = False

    def flush(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._process_queue()

    def clear(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._queue.clear()
            self._processing = False

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)


_memory_queue: Optional[MemoryUpdateQueue] = None
_queue_lock = threading.Lock()


def get_memory_queue() -> MemoryUpdateQueue:
    global _memory_queue
    with _queue_lock:
        if _memory_queue is None:
            _memory_queue = MemoryUpdateQueue()
        return _memory_queue


def reset_memory_queue() -> None:
    global _memory_queue
    with _queue_lock:
        if _memory_queue is not None:
            _memory_queue.clear()
        _memory_queue = None
