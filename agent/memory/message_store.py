"""Session message store (Redis) for multi-turn flash / chat history.

Storage: Redis LIST of JSON message blobs (RPUSH + LTRIM).
Atomic append avoids lost updates under concurrent same-session writes.
Legacy whole-JSON string keys are migrated on first load.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.memory.redis_memory import memoryRedis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "session:"
_KEY_SUFFIX = ":messages"
_DEFAULT_TTL = 7 * 24 * 3600  # 7 days
_MAX_MESSAGES = 50
_PROMPT_MSG_LIMIT = 16
_PROMPT_CONTENT_CHARS = 1200
_TOOL_STORE_CHARS = 2000
_APPEND_RETRIES = 3


def _key(session_id: str) -> str:
    return f"{_KEY_PREFIX}{session_id}{_KEY_SUFFIX}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: str, limit: int) -> str:
    text = text or ""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + f"\n...(truncated {len(text) - limit} chars)"


def _client():
    return memoryRedis.redis.client


class MessageStore:
    """Redis LIST-backed transcript: session_id -> messages."""

    def __init__(
        self,
        *,
        ttl_seconds: int = _DEFAULT_TTL,
        max_messages: int = _MAX_MESSAGES,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_messages = max_messages

    def _migrate_legacy_if_needed(self, session_id: str) -> None:
        """If key holds old whole-JSON array (string), convert to LIST."""
        key = _key(session_id)
        r = _client()
        try:
            t = r.type(key)
            # decode_responses=True -> type is str "string"/"list"/...
            if t not in ("string", "none") and t != b"string":
                return
            if t in ("none", b"none") or not r.exists(key):
                return
            raw = r.get(key)
            if raw is None:
                return
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                return
            if not isinstance(data, list):
                return
            pipe = r.pipeline()
            pipe.delete(key)
            for item in data:
                if isinstance(item, dict):
                    pipe.rpush(key, json.dumps(item, ensure_ascii=False))
            if data:
                pipe.ltrim(key, -self.max_messages, -1)
                pipe.expire(key, self.ttl_seconds)
            pipe.execute()
            logger.info("message_store migrated legacy key session=%s n=%d", session_id, len(data))
        except Exception as e:
            logger.warning("message_store migrate failed session=%s: %s", session_id, e)

    def load(self, session_id: str, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if not session_id:
            return []
        key = _key(session_id)
        try:
            self._migrate_legacy_if_needed(session_id)
            r = _client()
            if limit is not None and limit > 0:
                raw_items = r.lrange(key, -limit, -1)
            else:
                raw_items = r.lrange(key, 0, -1)
        except Exception as e:
            logger.warning("message_store load failed session=%s: %s", session_id, e)
            return []
        msgs: List[Dict[str, Any]] = []
        for raw in raw_items or []:
            try:
                item = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict):
                msgs.append(item)
        return msgs

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        name: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        content_limit: Optional[int] = None,
    ) -> None:
        if not session_id:
            return
        body = content or ""
        if content_limit is not None:
            body = _clip(body, content_limit)
        msg: Dict[str, Any] = {
            "role": (role or "user").strip().lower(),
            "content": body,
            "ts": _now_iso(),
        }
        if name:
            msg["name"] = name
        if meta:
            msg["meta"] = meta
        payload = json.dumps(msg, ensure_ascii=False)
        key = _key(session_id)
        last_err: Optional[Exception] = None
        for attempt in range(1, _APPEND_RETRIES + 1):
            try:
                self._migrate_legacy_if_needed(session_id)
                r = _client()
                pipe = r.pipeline()
                pipe.rpush(key, payload)
                pipe.ltrim(key, -self.max_messages, -1)
                pipe.expire(key, self.ttl_seconds)
                pipe.execute()
                return
            except Exception as e:
                last_err = e
                logger.warning(
                    "message_store append retry=%d session=%s role=%s: %s",
                    attempt,
                    session_id,
                    role,
                    e,
                )
        if last_err:
            logger.warning(
                "message_store append failed session=%s role=%s: %s",
                session_id,
                role,
                last_err,
            )

    def append_user(self, session_id: str, content: str) -> None:
        self.append(session_id, "user", content)

    def append_assistant(self, session_id: str, content: str) -> None:
        self.append(session_id, "assistant", content, content_limit=8000)

    def append_tool(
        self,
        session_id: str,
        content: str,
        *,
        name: str = "",
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.append(
            session_id,
            "tool",
            content,
            name=name or None,
            meta=meta,
            content_limit=_TOOL_STORE_CHARS,
        )

    def append_error(self, session_id: str, error: str) -> None:
        """Close a failed turn so transcript is not left as orphan user/tool."""
        text = (error or "unknown error").strip()
        if len(text) > 1500:
            text = text[:1500] + "..."
        self.append_assistant(
            session_id,
            f"[error] {text}",
        )

    def clear(self, session_id: str) -> None:
        if not session_id:
            return
        try:
            memoryRedis.del_cache(_key(session_id))
        except Exception as e:
            logger.warning("message_store clear failed session=%s: %s", session_id, e)

    def format_for_prompt(
        self,
        session_id: str,
        *,
        limit: int = _PROMPT_MSG_LIMIT,
        content_chars: int = _PROMPT_CONTENT_CHARS,
        exclude_last_user: bool = True,
    ) -> str:
        """Format recent transcript for flash plan / synthesis."""
        msgs = self.load(session_id, limit=limit + (1 if exclude_last_user else 0))
        if not msgs:
            return ""
        if exclude_last_user and msgs and msgs[-1].get("role") == "user":
            # current turn user is already in user_input; avoid duplicate
            msgs = msgs[:-1]
        if not msgs:
            return ""
        lines: List[str] = []
        for m in msgs[-limit:]:
            role = m.get("role") or "user"
            name = m.get("name") or ""
            label = f"{role}({name})" if name and role == "tool" else role
            body = _clip(str(m.get("content") or ""), content_chars)
            lines.append(f"{label}: {body}")
        return "\n".join(lines).strip()


message_store = MessageStore()
