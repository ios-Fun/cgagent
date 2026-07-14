"""对话消息过滤与纠正/强化信号检测（对齐 deerflow）。"""

from __future__ import annotations

import re
from copy import copy
from typing import Any, List

_UPLOAD_BLOCK_RE = re.compile(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", re.IGNORECASE)

_CORRECTION_PATTERNS = (
    re.compile(r"\bthat(?:'s| is) (?:wrong|incorrect)\b", re.IGNORECASE),
    re.compile(r"\byou misunderstood\b", re.IGNORECASE),
    re.compile(r"\btry again\b", re.IGNORECASE),
    re.compile(r"\bredo\b", re.IGNORECASE),
    re.compile(r"不对"),
    re.compile(r"你理解错了"),
    re.compile(r"你理解有误"),
    re.compile(r"重试"),
    re.compile(r"重新来"),
    re.compile(r"换一种"),
    re.compile(r"改用"),
)

_REINFORCEMENT_PATTERNS = (
    re.compile(r"\byes[,.]?\s+(?:exactly|perfect|that(?:'s| is) (?:right|correct|it))\b", re.IGNORECASE),
    re.compile(r"\bperfect(?:[.!?]|$)", re.IGNORECASE),
    re.compile(r"\bexactly\s+(?:right|correct)\b", re.IGNORECASE),
    re.compile(r"\bthat(?:'s| is)\s+(?:exactly\s+)?(?:right|correct|what i (?:wanted|needed|meant))\b", re.IGNORECASE),
    re.compile(r"\bkeep\s+(?:doing\s+)?that\b", re.IGNORECASE),
    re.compile(r"\bthis is (?:great|helpful)\b(?:[.!?]|$)", re.IGNORECASE),
    re.compile(r"对[，,]?\s*就是这样(?:[。！？!?.]|$)"),
    re.compile(r"完全正确(?:[。！？!?.]|$)"),
    re.compile(r"(?:对[，,]?\s*)?就是这个意思(?:[。！？!?.]|$)"),
    re.compile(r"正是我想要的(?:[。！？!?.]|$)"),
    re.compile(r"继续保持(?:[。！？!?.]|$)"),
)


def extract_message_text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
        role = message.get("role") or message.get("type")
    else:
        content = getattr(message, "content", "")
        role = getattr(message, "type", None) or getattr(message, "role", None)

    if isinstance(content, list):
        text_parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                text_val = part.get("text")
                if isinstance(text_val, str):
                    text_parts.append(text_val)
        return " ".join(text_parts)
    return str(content) if content is not None else ""


def _msg_type(message: Any) -> str:
    if isinstance(message, dict):
        role = message.get("type") or message.get("role") or ""
    else:
        role = getattr(message, "type", None) or getattr(message, "role", None) or ""
    role = str(role).lower()
    if role in ("human", "user"):
        return "human"
    if role in ("ai", "assistant"):
        return "ai"
    if role == "system":
        return "system"
    return role


def filter_messages_for_memory(messages: List[Any]) -> List[Any]:
    """只保留用户输入与最终助手回复。"""
    filtered: List[Any] = []
    skip_next_ai = False
    for msg in messages:
        msg_type = _msg_type(msg)
        if msg_type == "human":
            if isinstance(msg, dict) and msg.get("hide_from_ui"):
                continue
            if not isinstance(msg, dict) and getattr(msg, "additional_kwargs", {}).get("hide_from_ui"):
                continue
            content_str = extract_message_text(msg)
            if "<uploaded_files>" in content_str:
                stripped = _UPLOAD_BLOCK_RE.sub("", content_str).strip()
                if not stripped:
                    skip_next_ai = True
                    continue
                if isinstance(msg, dict):
                    clean_msg = {**msg, "content": stripped}
                else:
                    clean_msg = copy(msg)
                    clean_msg.content = stripped
                filtered.append(clean_msg)
                skip_next_ai = False
            else:
                filtered.append(msg)
                skip_next_ai = False
        elif msg_type == "ai":
            tool_calls = None
            if not isinstance(msg, dict):
                tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                if skip_next_ai:
                    skip_next_ai = False
                    continue
                filtered.append(msg)
    return filtered


def detect_correction(messages: List[Any]) -> bool:
    recent = [m for m in messages[-6:] if _msg_type(m) == "human"]
    for msg in recent:
        content = extract_message_text(msg).strip()
        if content and any(p.search(content) for p in _CORRECTION_PATTERNS):
            return True
    return False


def detect_reinforcement(messages: List[Any]) -> bool:
    recent = [m for m in messages[-6:] if _msg_type(m) == "human"]
    for msg in recent:
        content = extract_message_text(msg).strip()
        if content and any(p.search(content) for p in _REINFORCEMENT_PATTERNS):
            return True
    return False
