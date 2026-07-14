"""记忆更新 / 注入提示词（对齐 deerflow 结构，token 用字符估算）。"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MEMORY_UPDATE_PROMPT = """You are a memory management system. Your task is to analyze a conversation and update the user's memory profile.

Current Memory State:
<current_memory>
{current_memory}
</current_memory>

New Conversation to Process:
<conversation>
{conversation}
</conversation>

Instructions:
1. Analyze the conversation for important information about the user
2. Extract relevant facts, preferences, and context with specific details (numbers, names, technologies)
3. Update the memory sections as needed following the detailed length guidelines below

Before extracting facts, perform a structured reflection on the conversation:
1. Error/Retry Detection: Did the agent encounter errors, require retries, or produce incorrect results?
   If yes, record the root cause and correct approach as a high-confidence fact with category "correction".
2. User Correction Detection: Did the user correct the agent's direction, understanding, or output?
   If yes, record the correct interpretation or approach as a high-confidence fact with category "correction".
3. Project Constraint Discovery: Were any project-specific constraints discovered during the conversation?
   If yes, record them as facts with the most appropriate category and confidence.

{correction_hint}

Memory Section Guidelines:

**User Context** (Current state - concise summaries):
- workContext: Professional role, company, key projects, main technologies (2-3 sentences)
- personalContext: Languages, communication preferences, key interests (1-2 sentences)
- topOfMind: Multiple ongoing focus areas and priorities (3-5 sentences)

**History** (Temporal context):
- recentMonths: Recent activities (4-6 sentences)
- earlierContext: Historical patterns (3-5 sentences)
- longTermBackground: Persistent background (2-4 sentences)

**Facts Extraction**:
- Categories: preference | knowledge | context | behavior | goal | correction
- Confidence: 0.9-1.0 explicit; 0.7-0.8 strongly implied; 0.5-0.6 inferred

Output Format (JSON):
{{
  "user": {{
    "workContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "personalContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "topOfMind": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "history": {{
    "recentMonths": {{ "summary": "...", "shouldUpdate": true/false }},
    "earlierContext": {{ "summary": "...", "shouldUpdate": true/false }},
    "longTermBackground": {{ "summary": "...", "shouldUpdate": true/false }}
  }},
  "newFacts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ],
  "factsToRemove": ["fact_id_1"]
}}

Important Rules:
- Only set shouldUpdate=true if there's meaningful new information
- Only add facts clearly stated (0.9+) or strongly implied (0.7+)
- Remove facts contradicted by new information
- Do NOT record ephemeral session-only noise
- Return ONLY valid JSON, no explanation or markdown."""


FACT_EXTRACTION_PROMPT = """Extract factual information about the user from this message.

Message:
{message}

Extract facts in this JSON format:
{{
  "facts": [
    {{ "content": "...", "category": "preference|knowledge|context|behavior|goal|correction", "confidence": 0.0-1.0 }}
  ]
}}

Return ONLY valid JSON."""


def _count_tokens_char(text: str) -> int:
    """CJK 感知的字符估算（约 2 字/token 中文，4 字/token 英文）。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, int(cjk / 1.8 + other / 4.0))


def format_memory_for_injection(
    memory_data: Dict[str, Any],
    max_tokens: int = 2000,
    *,
    guaranteed_categories: Optional[List[str]] = None,
    guaranteed_token_budget: int = 500,
) -> str:
    """将画像格式化为系统提示词注入块。"""
    if not memory_data:
        return ""

    sections: List[str] = []
    user_data = memory_data.get("user") or {}
    if user_data:
        user_sections = []
        work_ctx = user_data.get("workContext") or {}
        if work_ctx.get("summary"):
            user_sections.append(f"Work: {work_ctx['summary']}")
        personal_ctx = user_data.get("personalContext") or {}
        if personal_ctx.get("summary"):
            user_sections.append(f"Personal: {personal_ctx['summary']}")
        top_of_mind = user_data.get("topOfMind") or {}
        if top_of_mind.get("summary"):
            user_sections.append(f"Current Focus: {top_of_mind['summary']}")
        if user_sections:
            sections.append("User Context:\n" + "\n".join(f"- {s}" for s in user_sections))

    history_data = memory_data.get("history") or {}
    if history_data:
        history_sections = []
        recent = history_data.get("recentMonths") or {}
        if recent.get("summary"):
            history_sections.append(f"Recent: {recent['summary']}")
        earlier = history_data.get("earlierContext") or {}
        if earlier.get("summary"):
            history_sections.append(f"Earlier: {earlier['summary']}")
        background = history_data.get("longTermBackground") or {}
        if background.get("summary"):
            history_sections.append(f"Background: {background['summary']}")
        if history_sections:
            sections.append("History:\n" + "\n".join(f"- {s}" for s in history_sections))

    facts_data = memory_data.get("facts") or []
    guaranteed_set = set(guaranteed_categories or [])
    if isinstance(facts_data, list) and facts_data:
        valid = [
            f for f in facts_data
            if isinstance(f, dict) and isinstance(f.get("content"), str) and f["content"].strip()
        ]

        def conf(f: dict) -> float:
            try:
                return float(f.get("confidence") or 0)
            except (TypeError, ValueError):
                return 0.0

        guaranteed = sorted(
            [f for f in valid if (f.get("category") or "").strip() in guaranteed_set],
            key=conf,
            reverse=True,
        )
        regular = sorted(
            [f for f in valid if (f.get("category") or "").strip() not in guaranteed_set],
            key=conf,
            reverse=True,
        )

        base_text = "\n\n".join(sections)
        base_tokens = _count_tokens_char(base_text) if base_text else 0
        fact_lines: List[str] = []
        used = base_tokens + _count_tokens_char("Facts:\n")

        def add_fact_lines(items: List[dict], budget: int) -> int:
            spent = 0
            for f in items:
                cat = f.get("category") or "context"
                line = f"- [{cat}|{conf(f):.2f}] {f['content'].strip()}"
                cost = _count_tokens_char(line + "\n")
                if spent + cost > budget:
                    break
                fact_lines.append(line)
                spent += cost
            return spent

        g_budget = min(guaranteed_token_budget, max(0, max_tokens - used))
        g_spent = add_fact_lines(guaranteed, g_budget) if guaranteed else 0
        r_budget = max(0, max_tokens - used - g_spent)
        if regular and r_budget > 0:
            add_fact_lines(regular, r_budget)

        if fact_lines:
            sections.append("Facts:\n" + "\n".join(fact_lines))

    if not sections:
        return ""

    result = "\n\n".join(sections)
    # 总长度保护
    while _count_tokens_char(result) > max_tokens and len(result) > 200:
        result = result[: int(len(result) * 0.9)].rstrip() + "\n..."
    header = "# 用户长期记忆（个性化上下文）\n以下信息来自该用户历史偏好与重要事实，请在回复中优先参考；无关可忽略，勿编造未列出信息。\n\n"
    return header + result


def format_conversation_for_update(messages: List[Any]) -> str:
    lines = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("type") or msg.get("role") or "unknown"
            content = msg.get("content", "")
        else:
            role = getattr(msg, "type", None) or getattr(msg, "role", "unknown")
            content = getattr(msg, "content", str(msg))

        if isinstance(content, list):
            text_parts = []
            for p in content:
                if isinstance(p, str):
                    text_parts.append(p)
                elif isinstance(p, dict) and isinstance(p.get("text"), str):
                    text_parts.append(p["text"])
            content = " ".join(text_parts) if text_parts else str(content)

        role = str(role).lower()
        if role in ("human", "user"):
            content = re.sub(r"<uploaded_files>[\s\S]*?</uploaded_files>\n*", "", str(content)).strip()
            if not content:
                continue
            if len(content) > 1000:
                content = content[:1000] + "..."
            lines.append(f"User: {content}")
        elif role in ("ai", "assistant"):
            content = str(content)
            if len(content) > 1000:
                content = content[:1000] + "..."
            lines.append(f"Assistant: {content}")

    return "\n\n".join(lines)
