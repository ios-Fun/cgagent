"""LLM 记忆更新器（对齐 deerflow，存储走 SQLite）。"""

from __future__ import annotations

import concurrent.futures
import copy
import json
import logging
import math
import re
import uuid
from typing import Any, Dict, List, Optional

from agent.memory.config import get_memory_config
from agent.memory.prompt import MEMORY_UPDATE_PROMPT, format_conversation_for_update
from agent.memory.storage import create_empty_memory, get_memory_storage, utc_now_iso_z

logger = logging.getLogger(__name__)

_SYNC_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="memory-updater",
)

_REQUIRED_KEYS = frozenset({"user", "history", "newFacts", "factsToRemove"})


def get_memory_data(agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
    return get_memory_storage().load(agent_name, user_id=user_id)


def reload_memory_data(agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
    return get_memory_storage().reload(agent_name, user_id=user_id)


def clear_memory_data(agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
    empty = create_empty_memory()
    if not get_memory_storage().save(empty, agent_name, user_id=user_id):
        raise OSError("Failed to clear memory")
    return empty


def delete_memory_fact(fact_id: str, agent_name: str | None = None, *, user_id: str | None = None) -> Dict[str, Any]:
    memory_data = get_memory_data(agent_name, user_id=user_id)
    facts = memory_data.get("facts", [])
    updated = [f for f in facts if f.get("id") != fact_id]
    if len(updated) == len(facts):
        raise KeyError(fact_id)
    memory_data = dict(memory_data)
    memory_data["facts"] = updated
    if not get_memory_storage().save(memory_data, agent_name, user_id=user_id):
        raise OSError("Failed to save after delete fact")
    return memory_data


def create_memory_fact(
    content: str,
    category: str = "context",
    confidence: float = 0.5,
    agent_name: str | None = None,
    *,
    user_id: str | None = None,
) -> Dict[str, Any]:
    content = content.strip()
    if not content:
        raise ValueError("content")
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise ValueError("confidence")
    now = utc_now_iso_z()
    memory_data = get_memory_data(agent_name, user_id=user_id)
    facts = list(memory_data.get("facts", []))
    facts.append(
        {
            "id": f"fact_{uuid.uuid4().hex[:8]}",
            "content": content,
            "category": category.strip() or "context",
            "confidence": confidence,
            "createdAt": now,
            "source": "manual",
        }
    )
    memory_data = dict(memory_data)
    memory_data["facts"] = facts
    if not get_memory_storage().save(memory_data, agent_name, user_id=user_id):
        raise OSError("Failed to save fact")
    return memory_data


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for block in content:
            if isinstance(block, str):
                pieces.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                pieces.append(block["text"])
        return "\n".join(pieces)
    return str(content)


def _normalize_fact(fact: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(fact, dict):
        return None
    raw = fact.get("content")
    if not isinstance(raw, str) or not raw.strip():
        return None
    cat = fact.get("category")
    category = cat.strip() if isinstance(cat, str) and cat.strip() else "context"
    conf = fact.get("confidence", 0.5)
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(conf):
        return None
    out = {"content": raw.strip(), "category": category, "confidence": conf}
    se = fact.get("sourceError")
    if isinstance(se, str) and se.strip():
        out["sourceError"] = se.strip()
    return out


def _parse_memory_update_response(response_content: Any) -> Dict[str, Any]:
    text = _extract_text(response_content).strip()
    # 去掉 markdown fence
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and _REQUIRED_KEYS.issubset(parsed):
            new_facts = []
            raw_facts = parsed.get("newFacts")
            if isinstance(raw_facts, list):
                for f in raw_facts:
                    nf = _normalize_fact(f)
                    if nf:
                        new_facts.append(nf)
            remove = parsed.get("factsToRemove")
            remove_ids = [x for x in remove if isinstance(x, str)] if isinstance(remove, list) else []
            return {
                "user": parsed.get("user") if isinstance(parsed.get("user"), dict) else {},
                "history": parsed.get("history") if isinstance(parsed.get("history"), dict) else {},
                "newFacts": new_facts,
                "factsToRemove": remove_ids,
            }
    raise json.JSONDecodeError("No valid memory update JSON", text, 0)


def _fact_key(content: Any) -> Optional[str]:
    if not isinstance(content, str):
        return None
    s = content.strip()
    return s.casefold() if s else None


def _apply_rule_fallback(
    current: Dict[str, Any],
    messages: List[Any],
    thread_id: Optional[str],
) -> Dict[str, Any]:
    """规则兜底：从用户句中抽偏好/背景。"""
    from agent.memory.long_term_memory import extract_memories_from_text

    user_texts = []
    for m in messages:
        if isinstance(m, dict):
            role = m.get("role") or m.get("type")
            content = m.get("content", "")
        else:
            role = getattr(m, "role", None) or getattr(m, "type", None)
            content = getattr(m, "content", "")
        if str(role).lower() in ("user", "human") and content:
            user_texts.append(str(content))

    if not user_texts:
        return current

    config = get_memory_config()
    now = utc_now_iso_z()
    memory = copy.deepcopy(current)
    existing = {
        k for k in (_fact_key(f.get("content")) for f in memory.get("facts", [])) if k
    }
    for text in user_texts:
        for item in extract_memories_from_text(text, session_id=thread_id):
            key = _fact_key(item.content)
            if not key or key in existing:
                continue
            cat_map = {
                "preference": "preference",
                "background": "context",
                "fact": "context",
                "event": "context",
            }
            conf = min(0.95, 0.5 + item.importance * 0.1)
            if conf < config.fact_confidence_threshold:
                continue
            memory.setdefault("facts", []).append(
                {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": item.content,
                    "category": cat_map.get(item.memory_type, "context"),
                    "confidence": conf,
                    "createdAt": now,
                    "source": thread_id or "rule",
                }
            )
            existing.add(key)

    if len(memory.get("facts", [])) > config.max_facts:
        memory["facts"] = sorted(
            memory["facts"], key=lambda f: f.get("confidence", 0), reverse=True
        )[: config.max_facts]
    return memory


class MemoryUpdater:
    def __init__(self, model_name: Optional[str] = None):
        self._model_name = model_name

    def _get_model(self):
        from langchain_ollama import ChatOllama

        config = get_memory_config()
        return ChatOllama(
            model=self._model_name or config.llm_model,
            base_url=config.llm_base_url,
            temperature=config.llm_temperature,
        )

    def _build_correction_hint(self, correction: bool, reinforcement: bool) -> str:
        parts = []
        if correction:
            parts.append(
                'IMPORTANT: Explicit correction signals were detected. '
                'Record correct approach as category "correction" with confidence >= 0.95 when appropriate.'
            )
        if reinforcement:
            parts.append(
                'IMPORTANT: Positive reinforcement detected. '
                'Record confirmed preference/behavior with confidence >= 0.9.'
            )
        return "\n".join(parts)

    def _apply_updates(
        self,
        current_memory: Dict[str, Any],
        update_data: Dict[str, Any],
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        config = get_memory_config()
        now = utc_now_iso_z()

        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory.setdefault("user", {})[section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory.setdefault("history", {})[section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        remove_ids = set(update_data.get("factsToRemove") or [])
        if remove_ids:
            current_memory["facts"] = [
                f for f in current_memory.get("facts", []) if f.get("id") not in remove_ids
            ]

        existing_keys = {
            k for k in (_fact_key(f.get("content")) for f in current_memory.get("facts", [])) if k
        }
        for fact in update_data.get("newFacts") or []:
            conf = float(fact.get("confidence", 0.5))
            if conf < config.fact_confidence_threshold:
                continue
            content = (fact.get("content") or "").strip()
            key = _fact_key(content)
            if not key or key in existing_keys:
                continue
            entry = {
                "id": f"fact_{uuid.uuid4().hex[:8]}",
                "content": content,
                "category": fact.get("category", "context"),
                "confidence": conf,
                "createdAt": now,
                "source": thread_id or "unknown",
            }
            if fact.get("sourceError"):
                entry["sourceError"] = fact["sourceError"]
            current_memory.setdefault("facts", []).append(entry)
            existing_keys.add(key)

        if len(current_memory.get("facts", [])) > config.max_facts:
            current_memory["facts"] = sorted(
                current_memory["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]
        return current_memory

    def _do_update_memory_sync(
        self,
        messages: List[Any],
        thread_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: Optional[str] = None,
    ) -> bool:
        config = get_memory_config()
        if not config.enabled or not messages or not user_id:
            return False

        current = get_memory_data(agent_name, user_id=user_id)
        conversation_text = format_conversation_for_update(messages)
        if not conversation_text.strip():
            return False

        if config.use_llm_update:
            try:
                prompt = MEMORY_UPDATE_PROMPT.format(
                    current_memory=json.dumps(current, indent=2, ensure_ascii=False),
                    conversation=conversation_text,
                    correction_hint=self._build_correction_hint(
                        correction_detected, reinforcement_detected
                    ),
                )
                model = self._get_model()
                response = model.invoke(prompt)
                update_data = _parse_memory_update_response(response.content)
                updated = self._apply_updates(copy.deepcopy(current), update_data, thread_id)
                return get_memory_storage().save(updated, agent_name, user_id=user_id)
            except Exception as e:
                logger.warning("LLM memory update failed, fallback=%s: %s", config.use_rule_fallback, e)
                if not config.use_rule_fallback:
                    return False

        if config.use_rule_fallback:
            updated = _apply_rule_fallback(current, messages, thread_id)
            return get_memory_storage().save(updated, agent_name, user_id=user_id)
        return False

    def update_memory(
        self,
        messages: List[Any],
        thread_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        correction_detected: bool = False,
        reinforcement_detected: bool = False,
        user_id: Optional[str] = None,
    ) -> bool:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            fut = _SYNC_EXECUTOR.submit(
                self._do_update_memory_sync,
                messages=messages,
                thread_id=thread_id,
                agent_name=agent_name,
                correction_detected=correction_detected,
                reinforcement_detected=reinforcement_detected,
                user_id=user_id,
            )
            return fut.result(timeout=120)

        return self._do_update_memory_sync(
            messages=messages,
            thread_id=thread_id,
            agent_name=agent_name,
            correction_detected=correction_detected,
            reinforcement_detected=reinforcement_detected,
            user_id=user_id,
        )


def update_memory_from_conversation(
    messages: List[Any],
    thread_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    correction_detected: bool = False,
    reinforcement_detected: bool = False,
    user_id: Optional[str] = None,
) -> bool:
    return MemoryUpdater().update_memory(
        messages,
        thread_id,
        agent_name,
        correction_detected,
        reinforcement_detected,
        user_id=user_id,
    )
