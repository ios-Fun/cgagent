"""flash mode: skill-policy driven."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

from agent.mcp.mcptools import get_mcp_tools
from agent.modes.common import (
    format_mcp_catalog,
    format_tool_args_for_prompt,
    invoke_mcp,
    parse_json,
    resolve_step_params,
    resolve_tool,
    tool_needs_params,
)

logger = logging.getLogger(__name__)

# Max agent turns per skill (call_mcp / analyze / done)
MAX_SKILL_TURNS = 12
# Max MCP calls when no skill matched (ad-hoc tool path)
MAX_ADHOC_MCP_CALLS = 3
# Total context budget for policy LLM (chars)
RESULT_SNIPPET_LIMIT = 50000
# Per tool-result note budget (avoid one 11k dump wiping older steps)
MAX_TOOL_NOTE_CHARS = 10000


async def execution_flash(coordinator: Any, session_id: str, user_input: str) -> str:

    coordinator.context.set_component("planner")
    logger.info("flash mode: skill routing")

    from agent.memory.message_store import message_store

    session_history = message_store.format_for_prompt(session_id)
    if session_history:
        # 仅本地传参用；勿 write_layer1（此时 component=planner，无写权限）
        logger.info("flash: session history chars=%d", len(session_history))

    available_skills = coordinator.skill_registry.get_all_skills()
    mcp_tools_cache = await get_mcp_tools()
    mcp_catalog = format_mcp_catalog(mcp_tools_cache)
    system_inventory = format_system_inventory(available_skills, mcp_tools_cache, mcp_catalog)

    # 系统能力类问题
    if is_system_capability_query(user_input):
        logger.info("flash: system capability query")
        coordinator._metrics["successful_plans"] += 1
        return (
            f"## 系统能力清单（请据此如实回答用户，勿编造清单外能力）\n"
            f"{system_inventory}"
        )

    route = route_skills(
        coordinator,
        user_input,
        available_skills,
        mcp_catalog=mcp_catalog,
        session_history=session_history,
    )
    coordinator.context.write_layer1("skill_route", route, "planner")
    coordinator.context.write_layer1("parsed_intent", route.get("intent", ""), "planner")

    path = (route.get("path") or "mcp").lower()
    skill_names = route.get("skills") or []
    if path != "skill":
        skill_names = []
    logger.info(
        "flash route: path=%s skills=%s intent=%s",
        path,
        skill_names,
        route.get("intent"),
    )

    if path != "skill" or not skill_names:
        coordinator.context.set_component("executor")
        if path != "direct" and mcp_tools_cache:
            logger.info("flash: MCP-first path (adhoc tools)")
            adhoc = await run_adhoc_mcp(
                coordinator,
                user_input=user_input,
                session_id=session_id,
                mcp_tools_cache=mcp_tools_cache,
                mcp_catalog=mcp_catalog,
                intent=route.get("intent") or "",
            )
            if adhoc:
                coordinator._metrics["successful_plans"] += 1
                return adhoc
        # direct / adhoc 无结果：只交参考内容，由 generate_context 成文（可带记忆）
        coordinator._metrics["successful_plans"] += 1
        hint = (route.get("direct_answer") or "").strip()
        intent = (route.get("intent") or "").strip()
        parts = [
            "## 无 skill / 无有效 MCP 取数结果",
            f"用户问题: {user_input}",
            f"意图: {intent or '未标注'}",
            f"path: {path}",
        ]
        if hint:
            parts.append(f"路由提示: {hint}")
        if path == "direct":
            parts.append(
                "说明: 该问题无需业务取数，请直接用专业中文回答用户。"
            )
        else:
            parts.append(
                "说明: 未能通过 MCP 取得有效业务数据；请据实说明，勿编造。"
            )
        return "\n".join(parts)

    coordinator.context.set_component("executor")
    result_parts: List[str] = []

    for skill_name in skill_names:
        if not skill_name:
            continue
        skill = available_skills.get(skill_name) if available_skills else None
        if skill is None:
            try:
                skill = coordinator.skill_registry.get_skill(skill_name)
            except Exception:
                skill = None
        if skill is None:
            logger.warning("flash: skill %s not found, skip", skill_name)
            continue

        logger.info("flash execute skill-policy2=%s", skill_name)
        skill_output = await run_skill_policy2(
            coordinator,
            skill=skill,
            user_input=user_input,
            session_id=session_id,
            mcp_tools_cache=mcp_tools_cache,
            mcp_catalog=mcp_catalog,
            prior_results="\n\n".join(result_parts),
            session_history=session_history,
        )
        if skill_output:
            result_parts.append(skill_output)
        coordinator._metrics["total_skills_executed"] += 1

    # skill 无有效输出时回退 MCP，避免空转
    if not result_parts and mcp_tools_cache:
        logger.info("flash: skill produced nothing; fallback adhoc MCP")
        adhoc = await run_adhoc_mcp(
            coordinator,
            user_input=user_input,
            session_id=session_id,
            mcp_tools_cache=mcp_tools_cache,
            mcp_catalog=mcp_catalog,
            intent=route.get("intent") or "",
        )
        if adhoc:
            coordinator._metrics["successful_plans"] += 1
            return adhoc

    coordinator._metrics["successful_plans"] += 1
    # skill_output 仅作「参考内容」；最终由 coordinator + 系统提示词再合成用户回答
    data_block = "\n\n".join(
        f"## Skill 参考输出 {i + 1}\n{part}"
        for i, part in enumerate(result_parts)
        if part and str(part).strip()
    ).strip()
    if not data_block:
        data_block = (
            "(skill 执行未产生有效参考内容；可能取数失败或未命中业务数据。"
            "请据实说明暂无法完成分析，并提示用户核对机组/设备名称或稍后重试。)"
        )
    logger.info(
        "flash execution finished, reference chars=%d skills=%d",
        len(data_block),
        len(result_parts),
    )
    return data_block


def is_system_capability_query(user_input: str) -> bool:
    """True if user asks what skills/MCP/capabilities the system has."""
    q = (user_input or "").strip().lower()
    if not q:
        return False
    # strong phrases
    phrases = (
        "有哪些skill", "有哪些技能", "可用技能", "技能列表", "skill列表",
        "有哪些mcp", "有哪些工具", "可用工具", "工具列表", "mcp列表", "mcp工具",
        "系统能力", "你能做什么", "你会什么", "支持哪些", "有什么功能",
        "能干什么", "有哪些功能", "能力列表", "what can you", "available skill",
        "available tool", "list skill", "list tool", "list mcp",
    )
    compact = q.replace(" ", "").replace("　", "")
    for p in phrases:
        if p.replace(" ", "") in compact or p in q:
            return True
    # soft: 技能/工具/mcp + 问询词
    has_obj = any(k in compact for k in ("skill", "技能", "mcp", "工具", "功能", "能力"))
    has_ask = any(k in compact for k in ("哪些", "什么", "列出", "介绍", "有没有", "支持", "可用"))
    return has_obj and has_ask


def format_system_inventory(
    available_skills: Dict,
    mcp_tools_cache: list,
    mcp_catalog: str,
) -> str:
    """Human-readable inventory of skills + MCP tools for capability Q&A."""
    skill_lines = []
    for name, skill in (available_skills or {}).items():
        desc = (getattr(skill, "description", None) or "").strip().replace("\n", " ")
        if len(desc) > 200:
            desc = desc[:200] + "..."
        tools = getattr(skill, "tools", None) or []
        skill_lines.append(f"- {name}: {desc or '(无描述)'}")
        if tools:
            # only show a few declared tool names
            shown = ", ".join(str(t) for t in tools[:12])
            if len(tools) > 12:
                shown += f" ...(+{len(tools)-12})"
            skill_lines.append(f"  关联工具(摘自SKILL): {shown}")
    skills_block = "\n".join(skill_lines) if skill_lines else "(当前未加载任何 skill)"

    mcp_names = []
    for t in mcp_tools_cache or []:
        n = getattr(t, "name", None)
        if n:
            mcp_names.append(n)
    mcp_block = "\n".join(f"- {n}" for n in mcp_names) if mcp_names else "(当前未加载任何 MCP 工具)"
    # optional short catalog with types if not too long
    catalog_extra = ""
    if mcp_catalog and len(mcp_catalog) < 4000:
        catalog_extra = f"\n\nMCP 明细（含参数类型）:\n{mcp_catalog}"

    return (
        f"## 可用 Skills（共 {len(available_skills or {})} 个）\n{skills_block}\n\n"
        f"## 可用 MCP 工具（共 {len(mcp_names)} 个）\n{mcp_block}"
        f"{catalog_extra}"
    )



def plan_adhoc_mcps(
    coordinator: Any,
    *,
    user_input: str,
    mcp_catalog: str,
    intent: str = "",
) -> Dict[str, Any]:
    """MCP-first path: pick tools for simple data queries."""
    catalog = (mcp_catalog or "")[:6000]
    prompt = f"""你是 MCP 工具路由器。
你的职责：
根据用户问题选择最少、最直接满足需求的 MCP 工具。
你只负责选择工具，不填写参数，不回答用户。
用户问题：
{user_input}
意图：
{intent or "未标注"}
可用 MCP 工具目录：
{catalog}
规则：
1. 需要业务数据（诊断单、报警、测点、列表、实时值等）且目录有合适工具 → need_tools=true。
2. 工具选择原则：
   - 优先选择一个最直接满足需求的工具；
   - 除非用户明确要求综合分析，否则不要选择多个工具；
   - 不为了补充分析而额外调用无关工具。
3. 如果用户问题属于已有 Skill 流程：
   - 选择符合 Skill 相关的 MCP，以扩展数据内容；
   - 不自行扩展业务分析流程。
4. 以下情况：
   - 闲聊；
   - 概念解释；
   - 无业务数据需求；
   - 查询对象无法确定；
   need_tools=false。
6. 不输出 params。
7. 只输出 JSON。
输出：
{
"need_tools": false,
  "reason": "选择原因",
  "tools": [
    {
"mcp": "tool_name",
      "purpose": "调用目的"
    }
  ]
}
"""
    try:
        raw = coordinator.llm_client.invoke(prompt, temperature=0.1, max_tokens=800)
        data = parse_json(raw)
        if not isinstance(data, dict):
            return {"need_tools": False, "tools": []}
        tools = data.get("tools") or []
        if not isinstance(tools, list):
            tools = []
        cleaned = []
        for item in tools[:MAX_ADHOC_MCP_CALLS]:
            if isinstance(item, str):
                cleaned.append({"mcp": item, "purpose": ""})
            elif isinstance(item, dict) and (item.get("mcp") or item.get("tool")):
                cleaned.append({
                    "mcp": item.get("mcp") or item.get("tool"),
                    "purpose": item.get("purpose") or item.get("reason") or "",
                })
        return {
            "need_tools": bool(data.get("need_tools")) and bool(cleaned),
            "reason": data.get("reason") or "",
            "tools": cleaned if data.get("need_tools") else [],
        }
    except Exception as e:
        logger.warning("plan_adhoc_mcps failed: %s", e, exc_info=True)
        return {"need_tools": False, "tools": []}


async def run_adhoc_mcp(
    coordinator: Any,
    *,
    user_input: str,
    session_id: str,
    mcp_tools_cache: list,
    mcp_catalog: str,
    intent: str = "",
) -> str:
    """No skill but MCP may fit: select tools -> fill params -> invoke -> answer with evidence."""
    if not mcp_tools_cache:
        return ""

    plan = plan_adhoc_mcps(
        coordinator,
        user_input=user_input,
        mcp_catalog=mcp_catalog,
        intent=intent,
    )
    tools = plan.get("tools") or []
    if not plan.get("need_tools") or not tools:
        logger.info("flash adhoc: no tools needed reason=%s", plan.get("reason"))
        return ""

    logger.info(
        "flash adhoc: tools=%s reason=%s",
        [t.get("mcp") for t in tools],
        plan.get("reason"),
    )
    from agent.memory.message_store import message_store

    notes: List[str] = []
    executed: Set[str] = set()

    for item in tools:
        mcp_name = item.get("mcp") or item.get("tool")
        if not mcp_name or mcp_name in executed:
            continue
        tool = resolve_tool(mcp_name, mcp_tools_cache, coordinator)
        if tool is None:
            logger.warning("flash adhoc: tool not found %s", mcp_name)
            continue
        real_name = getattr(tool, "name", mcp_name)
        purpose = item.get("purpose") or ""
        params = resolve_params_for_mcp(
            coordinator,
            mcp_name=real_name,
            mcp_tools_cache=mcp_tools_cache,
            user_input=user_input,
            session_id=session_id,
            purpose=purpose,
            accumulated_results="\n\n".join(notes),
        )
        step_text = await invoke_mcp(
            coordinator,
            session_id=session_id,
            user_input=user_input,
            mcp_name=real_name,
            mcp_tools_cache=mcp_tools_cache,
            params_hint=params,
        )
        executed.add(real_name)
        notes.append(_format_tool_note(real_name, step_text))
        # 空/失败也写入，便于追问看到「调过但无数据」
        status = _classify_tool_result_status(step_text or "")
        message_store.append_tool(
            session_id,
            step_text or f"(empty/error status={status})",
            name=str(real_name),
            meta={"path": "adhoc", "purpose": purpose, "status": status},
        )
        coordinator._metrics["total_skills_executed"] = (
            coordinator._metrics.get("total_skills_executed", 0)
        )

    evidence = build_policy_context(notes, limit=RESULT_SNIPPET_LIMIT)
    if not _notes_have_tool(notes):
        logger.info("flash adhoc: no tool notes")
        return ""

    if not _notes_have_ok(notes):
        # 全失败/全空：仍返回证据，交给合成层据实说明，勿吞成空串走闲聊
        logger.info("flash adhoc: tools ran but no status=ok results")
        return (
            f"## MCP 查询结果（未取得有效业务数据）\n"
            f"意图: {intent or '未标注'}\n"
            f"说明: 工具已调用，但结果为空或失败；请据实告知用户，勿编造数据。\n\n"
            f"{evidence}"
        )

    return (
        f"## MCP 查询结果\n"
        f"意图: {intent or '未标注'}\n\n"
        f"{evidence}"
    )


def _skill_policy_text(skill: Any) -> str:
    """Full skill guidance text for policy agent (body > workflow+prompt)."""
    body = (getattr(skill, "body", None) or "").strip()
    if body:
        return body[:12000]
    parts = []
    prompt = (getattr(skill, "prompt", None) or "").strip()
    workflow = (getattr(skill, "workflow", None) or "").strip()
    if prompt:
        parts.append(prompt)
    if workflow:
        parts.append(workflow)
    return "\n\n".join(parts)[:12000]


def _clip_text(text: str, limit: int) -> str:
    """Keep head + tail so both ids at start and late content remain visible."""
    text = text or ""
    if limit <= 0 or len(text) <= limit:
        return text
    head = max(limit // 2, 1)
    tail = max(limit - head - 40, 1)
    return (
        text[:head]
        + f"\n...[truncated {len(text) - head - tail} chars]...\n"
        + text[-tail:]
    )


def _classify_tool_result_status(text: str) -> str:
    """Classify tool payload: ok | empty | error (not every non-empty string is ok)."""
    body = (text or "").strip()
    if not body:
        return "empty"

    from agent.modes.common import _looks_like_tool_error

    if _looks_like_tool_error(body):
        return "error"

    low = body.lower()
    # common empty / no-data payloads
    empty_markers = (
        "[]",
        "{}",
        "null",
        "暂无数据",
        "无数据",
        "没有数据",
        "查询结果为空",
        "未查询到",
        "未找到",
        "no data",
        "empty list",
        "empty result",
    )
    compact = "".join(body.split())
    if compact in ("[]", "{}", "null", '""', "''"):
        return "empty"
    if any(m in body or m in low for m in empty_markers) and len(body) < 400:
        # short "no data" style replies
        if not any(ch.isdigit() for ch in body) or any(
            m in body for m in ("暂无", "无数据", "未查询", "未找到", "没有数据")
        ):
            return "empty"

    error_markers = (
        "调用失败",
        "请求失败",
        "参数错误",
        "参数校验",
        "无权",
        "unauthorized",
        "forbidden",
        "timeout",
        "timed out",
        "exception",
        "error:",
        "失败:",
        "http 4",
        "http 5",
        "status=500",
        "status=400",
    )
    if any(m in low or m in body for m in error_markers) and len(body) < 1500:
        return "error"

    return "ok"


def _format_tool_note(mcp_name: str, step_text: str) -> str:
    """Store tool result with size cap; status=ok|empty|error."""
    body = (step_text or "").strip()
    status = _classify_tool_result_status(body)
    if status == "empty" and not body:
        return (
            f"[tool:{mcp_name}]\n"
            f"status=empty\n"
            f"(无有效返回：可能参数错误、业务无数据或工具调用失败，"
            f"可重试/换工具/停止并告知用户)"
        )
    clipped = _clip_text(body, MAX_TOOL_NOTE_CHARS) if body else "(empty)"
    return (
        f"[tool:{mcp_name}]\n"
        f"status={status} chars={len(body)}\n"
        f"{clipped}"
    )


def _notes_have_ok(notes: List[str]) -> bool:
    return any("status=ok" in (n or "") for n in notes)


def _notes_have_tool(notes: List[str]) -> bool:
    return any((n or "").startswith("[tool:") for n in notes)


def build_policy_context(notes: List[str], limit: int = RESULT_SNIPPET_LIMIT) -> str:
    """Build policy context preferring **latest** notes (tool results), not only the head.

    Bug before: context[:limit] dropped the newest large tool output when early steps
    already filled the budget → model thought unit_tags_realtime never returned data.
    """
    if not notes:
        return ""
    # newest first packing
    selected_rev: List[str] = []
    used = 0
    for note in reversed(notes):
        piece = note
        # still cap each note
        if note.startswith("[tool:") and len(note) > MAX_TOOL_NOTE_CHARS + 80:
            # re-clip body if needed
            piece = note  # already clipped when stored
        sep = 2 if selected_rev else 0
        if used + sep + len(piece) > limit:
            remain = limit - used - sep - 40
            if remain < 200:
                # always try to keep at least a short marker of this note
                marker = piece[:120] + "\n...(note omitted due to context budget)"
                if used + sep + len(marker) <= limit:
                    selected_rev.append(marker)
                break
            piece = _clip_text(piece, remain)
        selected_rev.append(piece)
        used += sep + len(piece)
        if used >= limit:
            break
    selected = list(reversed(selected_rev))
    return "\n\n".join(selected).strip()


def _skill_allowed_tools(skill: Any, mcp_tools_cache: list) -> List[str]:
    """Only tools that exist in mcp_tools_cache (matched by real tool.name).

    SKILL.md may write short names like ``unit_tags_realtime``; cache may have
    ``mcp-device-sse_unit_tags_realtime``. Unmatched declared strings are dropped.
    """
    from agent.modes.common import tool_name_matches

    cache = list(mcp_tools_cache or [])
    cache_names = [getattr(t, "name", str(t)) for t in cache if getattr(t, "name", None)]
    declared = list(getattr(skill, "tools", None) or [])

    # No SKILL whitelist -> all loaded MCP tools
    if not declared:
        return list(cache_names)

    allowed: List[str] = []
    for declared_name in declared:
        if not declared_name or not isinstance(declared_name, str):
            continue
        # skip obvious non-tool backticks from markdown (too short / spaces / chinese only)
        d = declared_name.strip()
        if " " in d or len(d) < 3:
            continue
        matched = None
        for tool in cache:
            real = getattr(tool, "name", None)
            if real and tool_name_matches(d, real):
                matched = real
                break
        if matched is None:
            # also try resolve_tool for coordinator-style matching
            tool = resolve_tool(d, cache)
            if tool is not None:
                matched = getattr(tool, "name", None)
        if matched and matched not in allowed:
            allowed.append(matched)
        elif matched is None:
            logger.debug(
                "skill allowed tools: drop unmatched declared=%r (not in mcp cache)",
                d,
            )
    if not allowed:
        logger.warning(
            "skill %s: no declared tools matched mcp_tools_cache; falling back to all loaded tools",
            getattr(skill, "name", "?"),
        )
        return list(cache_names)
    return allowed


async def run_skill_policy(
    coordinator: Any,
    *,
    skill: Any,
    user_input: str,
    session_id: str,
    mcp_tools_cache: list,
    mcp_catalog: str,
    prior_results: str = "",
) -> str:
    """execution_flash
        └─ for skill: run_skill_policy(...)
           ├─ decide_skill_next_action   # 每轮就很烦 丢 我要弃用你了
           ├─ resolve_params_for_mcp
           ├─ invoke_mcp
           └─ _build_skill_evidence_package
        └─ 拼 result_parts
    """
    skill_name = getattr(skill, "name", "skill")
    policy = _skill_policy_text(skill)
    allowed_tools = _skill_allowed_tools(skill, mcp_tools_cache)
    allowed_set = set(allowed_tools)

    # catalog subset for allowed tools only
    allowed_catalog_lines = []
    for tool in mcp_tools_cache or []:
        name = getattr(tool, "name", str(tool))
        if name in allowed_set or any(
            name.endswith(a) or a.endswith(name) for a in allowed_tools
        ):
            desc = (getattr(tool, "description", None) or "")[:160]
            args = format_tool_args_for_prompt(tool)
            allowed_catalog_lines.append(f"- {name}: {desc}\n  args: {args}")
    tools_text = "\n".join(allowed_catalog_lines) if allowed_catalog_lines else (
        "allowed tool names: " + ", ".join(allowed_tools)
    )

    notes: List[str] = []
    if prior_results:
        notes.append(f"[prior]\n{prior_results[:3000]}")

    executed: Set[str] = set()
    last_action = ""
    final_user_text = ""

    for turn in range(1, MAX_SKILL_TURNS + 1):
        context = build_policy_context(notes, RESULT_SNIPPET_LIMIT)

        decision = decide_skill_next_action(
            coordinator,
            skill_name=skill_name,
            policy=policy,
            user_input=user_input,
            session_id=session_id,
            tools_text=tools_text,
            allowed_tools=allowed_tools,
            executed=sorted(executed),
            context=context,
            turn=turn,
        )
        action = (decision.get("action") or "").lower().strip()
        last_action = action
        logger.info(
            "flash skill=%s turn=%d action=%s reason=%s",
            skill_name,
            turn,
            action,
            (decision.get("reason") or "")[:120],
        )

        if action in ("stop", "final_answer", "done"):
            final_user_text = (
                decision.get("user_message")
                or decision.get("message")
                or decision.get("content")
                or ""
            ).strip()
            if final_user_text:
                notes.append(f"[final]\n{final_user_text}")
            break

        if action == "analyze":
            analysis = (
                decision.get("content")
                or decision.get("analysis")
                or decision.get("user_message")
                or ""
            ).strip()
            if analysis:
                notes.append(f"[analysis]\n{analysis}")
            continue

        if action == "call_mcp":
            mcp_name = decision.get("mcp") or decision.get("tool")
            if not mcp_name:
                notes.append("[policy] call_mcp missing tool name, skip")
                continue
            # allow only skill tools when list non-empty
            if allowed_tools and not any(
                mcp_name == a or mcp_name.endswith(a) or a.endswith(mcp_name)
                for a in allowed_tools
            ):
                logger.warning("flash skill=%s blocked mcp=%s", skill_name, mcp_name)
                notes.append(f"[policy] tool not allowed by skill: {mcp_name}")
                continue

            purpose = decision.get("purpose") or decision.get("reason") or ""
            params = resolve_params_for_mcp(
                coordinator,
                mcp_name=mcp_name,
                mcp_tools_cache=mcp_tools_cache,
                user_input=user_input,
                session_id=session_id,
                purpose=purpose,
                accumulated_results=context,
            )
            # optional overrides from policy decision
            if isinstance(decision.get("params"), dict) and decision["params"]:
                # only fill missing keys; prefer param-filler types
                for k, v in decision["params"].items():
                    if k not in params or params[k] is None:
                        params[k] = v

            step_text = await invoke_mcp(
                coordinator,
                session_id=session_id,
                user_input=user_input,
                mcp_name=mcp_name,
                mcp_tools_cache=mcp_tools_cache,
                params_hint=params,
            )
            executed.add(mcp_name)
            notes.append(_format_tool_note(mcp_name, step_text))
            continue

        # unknown action
        notes.append(f"[policy] unknown action: {action}")
        break

    return _build_skill_evidence_package(
        skill_name=skill_name,
        user_input=user_input,
        notes=notes,
        executed=sorted(executed),
        last_action=last_action,
        draft_final=final_user_text,
    )


def plan_skill_execution(
    coordinator: Any,
    *,
    skill_name: str,
    policy: str,
    user_input: str,
    session_id: str,
    tools_text: str,
    allowed_tools: List[str],
    prior_results: str = "",
    session_history: str = "",
) -> Dict[str, Any]:
    """One-shot plan for a skill: ordered steps (call_mcp / analyze / stop)."""
    prior = (prior_results or "").strip()
    if len(prior) > 3000:
        prior = prior[:3000] + "\n...(prior truncated)"
    history = (session_history or "").strip()
    if len(history) > 4000:
        history = history[:4000] + "\n...(history truncated)"
    policy_snip = (policy or "")[:8000]
    tools_snip = (tools_text or "")[:6000]
    allow_list = ", ".join(allowed_tools) if allowed_tools else "(all loaded)"

    prompt = f"""你是技能执行规划器（Skill Execution Planner）。
你的职责：
根据 Skill 权威规则、用户问题和已有上下文，为当前 Skill 生成执行计划。
你只负责规划执行路径，不执行工具，不填写参数，不生成最终答案。
---
当前 Skill：
{skill_name}
session_id:
{session_id}
---
# Skill 权威规则
{policy_snip}
---
# 用户问题
{user_input}
---
# 会话历史（多轮追问上下文，可空）
{history if history else "(空)"}
---
# 已有结果（本轮前序 skill / 工具）
{prior if prior else "(空)"}
---
# 可调用 MCP
{tools_snip}
允许工具：
{allow_list}
---
# 规划原则
1. Skill 是最高优先级规则。
必须严格遵守：
- Workflow；
- 分支条件；
- 停止条件；
- 必要分析步骤。
禁止：
- 绕过 Skill；
- 根据经验添加流程；
- 调用 Skill 未允许的工具。
---
2. 生成执行步骤：
steps 按执行顺序排列。
每一步只能是：
### call_mcp
表示需要调用工具获取数据。
要求：
- mcp 必须来自允许列表；
- purpose 说明获取什么信息；
- 不填写 params。
### analyze
表示已有数据，需要执行 Skill 要求的分析。
### stop
表示无法继续，需要用户补充信息或流程结束。
---
3. 规划要求：
- 优先最少步骤完成目标；
- 不重复调用相同工具；
- 必要前置步骤必须排在前面；
- 不提前规划依赖前置结果的步骤。
- 若会话历史已含足够工具/业务结果且用户在追问，可减少重复 call_mcp。
例如：
先确认设备存在，
再查询设备数据。
---
4. 条件流程：
如果后续步骤依赖前一步结果，用 condition 描述。
例如：
- 查询不到对象 → stop
- 无诊断数据 → 按 Skill 规则结束或进入补充流程
---
5. 不生成：
- params；
- 工具返回结果；
- 最终用户报告。
---
6. 只输出合法 JSON，不要 markdown。
输出格式：
{{
  "intent": "用户意图简述",
  "reason": "规划依据",
  "steps": [
    {{
      "action": "call_mcp",
      "mcp": "工具名",
      "purpose": "调用目的",
      "condition": ""
    }},
    {{
      "action": "analyze",
      "purpose": "分析目的",
      "condition": ""
    }},
    {{
      "action": "stop",
      "reason": "停止原因",
      "condition": ""
    }}
  ]
}}
"""
    try:
        raw = coordinator.llm_client.invoke(prompt, temperature=0.1, max_tokens=5000)
        data = parse_json(raw)
        if not isinstance(data, dict):
            raise ValueError("plan is not a dict")
        steps_raw = data.get("steps") or []
        if not isinstance(steps_raw, list):
            steps_raw = []
        steps: List[Dict[str, Any]] = []
        for item in steps_raw[:MAX_SKILL_TURNS]:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").lower().strip()
            if action not in ("call_mcp", "analyze", "stop", "final_answer", "done"):
                continue
            if action in ("final_answer", "done"):
                action = "stop"
            step: Dict[str, Any] = {
                "action": action,
                "purpose": item.get("purpose") or item.get("reason") or "",
            }
            if action == "call_mcp":
                mcp = item.get("mcp") or item.get("tool")
                if not mcp:
                    continue
                step["mcp"] = str(mcp).strip()
            if action == "stop":
                step["reason"] = item.get("reason") or item.get("purpose") or ""
            steps.append(step)
        return {
            "intent": data.get("intent") or "",
            "reason": data.get("reason") or "",
            "steps": steps,
        }
    except Exception as e:
        logger.warning("plan_skill_execution failed: %s", e, exc_info=True)
        return {"intent": "plan_failed", "reason": str(e), "steps": []}


def _fallback_steps_from_skill(skill: Any, allowed_tools: List[str]) -> List[Dict[str, Any]]:
    """If planner fails: call skill tools in order, then stop."""
    steps: List[Dict[str, Any]] = []
    declared = list(getattr(skill, "tools", None) or [])
    pool = allowed_tools or []
    from agent.modes.common import tool_name_matches

    for d in declared:
        if not d or not isinstance(d, str):
            continue
        matched = next((a for a in pool if tool_name_matches(d, a)), None)
        if matched is None and d in pool:
            matched = d
        if matched and not any(s.get("mcp") == matched for s in steps):
            steps.append({
                "action": "call_mcp",
                "mcp": matched,
                "purpose": f"from skill {getattr(skill, 'name', '')} default order",
            })
        if len(steps) >= MAX_SKILL_TURNS:
            break
    if not steps and pool:
        # last resort: first allowed tool only
        steps.append({
            "action": "call_mcp",
            "mcp": pool[0],
            "purpose": "fallback single tool",
        })
    steps.append({"action": "stop", "reason": "fallback plan end"})
    return steps[:MAX_SKILL_TURNS]


def _analyze_under_plan(
    coordinator: Any,
    *,
    skill_name: str,
    policy: str,
    user_input: str,
    purpose: str,
    context: str,
) -> str:
    """Optional mid-plan analysis (one short LLM call)."""
    ctx = (context or "")[:10000]
    pol = (policy or "")[:5000]
    prompt = f"""你是技能中间分析器。按 Skill 规则与已有工具结果做简短分析摘要（中文，≤1000字）。
不要编造工具未返回的数据。只输出分析正文，不要 JSON。
要注重数值型数据，最好输出要带原值。
Skill: {skill_name}
用户问题: {user_input}
本步目的: {purpose or "(综合分析)"}

Skill 规则摘录:
{pol}

已有上下文:
{ctx if ctx else "(空)"}
"""
    try:
        return (coordinator.llm_client.invoke(prompt, temperature=0.2, max_tokens=1200) or "").strip()
    except Exception as e:
        logger.warning("plan analyze failed: %s", e)
        return ""


async def run_skill_policy2(
    coordinator: Any,
    *,
    skill: Any,
    user_input: str,
    session_id: str,
    mcp_tools_cache: list,
    mcp_catalog: str,
    prior_results: str = "",
    session_history: str = "",
) -> str:
    """
        -- plan_skill_execution: skill全文 + 用户问题 + prior + 允许MCP → 有序 steps
        -- 按 steps 执行
           ├─ call_mcp → resolve_params_for_mcp(AI填参) → invoke_mcp
           ├─ analyze  → 短 LLM 摘要（可选）
           ├─ stop     → 结束
        -- _build_skill_evidence_package
    """
    from agent.memory.message_store import message_store

    skill_name = getattr(skill, "name", "skill")
    policy = _skill_policy_text(skill)
    allowed_tools = _skill_allowed_tools(skill, mcp_tools_cache)
    allowed_set = set(allowed_tools)
    if not session_history:
        session_history = message_store.format_for_prompt(session_id)

    allowed_catalog_lines = []
    for tool in mcp_tools_cache or []:
        name = getattr(tool, "name", str(tool))
        if name in allowed_set or any(
            name.endswith(a) or a.endswith(name) for a in allowed_tools
        ):
            desc = (getattr(tool, "description", None) or "")[:160]
            args = format_tool_args_for_prompt(tool)
            allowed_catalog_lines.append(f"- {name}: {desc}\n  args: {args}")
    tools_text = "\n".join(allowed_catalog_lines) if allowed_catalog_lines else (
        "allowed tool names: " + ", ".join(allowed_tools)
    )

    plan = plan_skill_execution(
        coordinator,
        skill_name=skill_name,
        policy=policy,
        user_input=user_input,
        session_id=session_id,
        tools_text=tools_text,
        allowed_tools=allowed_tools,
        prior_results=prior_results,
        session_history=session_history,
    )
    steps = plan.get("steps") or []
    if not steps:
        logger.warning("flash skill=%s empty plan; fallback tool order", skill_name)
        steps = _fallback_steps_from_skill(skill, allowed_tools)
    logger.info(
        "flash skill=%s plan intent=%s steps=%s reason=%s",
        skill_name,
        (plan.get("intent") or "")[:80],
        [(s.get("action"), s.get("mcp")) for s in steps],
        (plan.get("reason") or "")[:120],
    )

    notes: List[str] = []
    if session_history:
        notes.append(f"[session_history]\n{session_history[:4000]}")
    if prior_results:
        notes.append(f"[prior]\n{prior_results[:3000]}")
    notes.append(
        f"[plan]\nintent={plan.get('intent') or ''}\n"
        f"reason={plan.get('reason') or ''}\n"
        f"steps={[(s.get('action'), s.get('mcp'), s.get('purpose')) for s in steps]}"
    )

    executed: Set[str] = set()
    last_action = ""
    final_user_text = ""

    for i, step in enumerate(steps, start=1):
        action = (step.get("action") or "").lower().strip()
        last_action = action
        purpose = step.get("purpose") or step.get("reason") or ""
        context = build_policy_context(notes, RESULT_SNIPPET_LIMIT)
        logger.info(
            "flash skill=%s plan-step=%d/%d action=%s mcp=%s",
            skill_name,
            i,
            len(steps),
            action,
            step.get("mcp") or "",
        )

        if action in ("stop", "final_answer", "done"):
            final_user_text = (step.get("reason") or purpose or "").strip()
            if final_user_text:
                notes.append(f"[final]\n{final_user_text}")
            break

        if action == "analyze":
            analysis = _analyze_under_plan(
                coordinator,
                skill_name=skill_name,
                policy=policy,
                user_input=user_input,
                purpose=purpose,
                context=context,
            )
            if analysis:
                notes.append(f"[analysis]\n{analysis}")
            continue

        if action == "call_mcp":
            mcp_name = step.get("mcp") or step.get("tool")
            if not mcp_name:
                notes.append("[policy] call_mcp missing tool name, skip")
                continue
            if allowed_tools and not any(
                mcp_name == a or mcp_name.endswith(a) or a.endswith(mcp_name)
                for a in allowed_tools
            ):
                logger.warning("flash skill=%s blocked mcp=%s", skill_name, mcp_name)
                notes.append(f"[policy] tool not allowed by skill: {mcp_name}")
                continue

            params = resolve_params_for_mcp(
                coordinator,
                mcp_name=mcp_name,
                mcp_tools_cache=mcp_tools_cache,
                user_input=user_input,
                session_id=session_id,
                purpose=purpose,
                accumulated_results=context,
            )
            step_text = await invoke_mcp(
                coordinator,
                session_id=session_id,
                user_input=user_input,
                mcp_name=mcp_name,
                mcp_tools_cache=mcp_tools_cache,
                params_hint=params,
            )
            executed.add(str(mcp_name))
            notes.append(_format_tool_note(str(mcp_name), step_text))
            # 空/失败也写入，便于追问看到「调过但无数据」
            status = _classify_tool_result_status(step_text or "")
            message_store.append_tool(
                session_id,
                step_text or f"(empty/error status={status})",
                name=str(mcp_name),
                meta={
                    "skill": skill_name,
                    "purpose": purpose,
                    "status": status,
                },
            )
            continue

        notes.append(f"[policy] unknown plan action: {action}")
        break

    return _build_skill_evidence_package(
        skill_name=skill_name,
        user_input=user_input,
        notes=notes,
        executed=sorted(executed),
        last_action=last_action,
        draft_final=final_user_text,
    )


def _build_skill_evidence_package(
    *,
    skill_name: str,
    user_input: str,
    notes: List[str],
    executed: List[str],
    last_action: str = "",
    draft_final: str = "",
) -> str:
    """Package skill run as reference content for the synthesis layer."""
    evidence = build_policy_context(
        [n for n in notes if not (n or "").startswith("[prior]")],
        limit=RESULT_SNIPPET_LIMIT,
    )
    draft = (draft_final or "").strip()
    if len(draft) > 2000:
        draft = draft[:2000] + "\n...(draft truncated)"

    parts = [
        f"## Skill 执行证据: {skill_name}",
        f"用户问题: {user_input}",
        f"结束动作: {last_action or 'unknown'}",
        f"已调用工具: {executed or []}",
    ]
    if evidence:
        parts.append(f"\n### 工具结果与中间分析\n{evidence}")
    else:
        parts.append("\n### 工具结果与中间分析\n(无)")
    if draft:
        parts.append(f"\n### 策略备注（非最终用户报告）\n{draft}")
    return "\n".join(parts).strip()


def decide_skill_next_action(
    coordinator: Any,
    *,
    skill_name: str,
    policy: str,
    user_input: str,
    session_id: str,
    tools_text: str,
    allowed_tools: List[str],
    executed: List[str],
    context: str,
    turn: int,
) -> Dict[str, Any]:
    """One policy step: follow SKILL.md, not a bare MCP list."""
    prompt = f"""你是技能执行决策器（Skill Executor Decision Agent）。

你的职责不是直接回答用户问题，而是根据当前 Skill 定义、已有上下文和工具结果，决定下一步执行动作。

必须严格遵守：
- 当前 Skill 全文中的角色定义；
- 工作流程；
- 分支条件；
- 停止条件；
- 输出要求。
不要把 Skill 当作工具说明，而要把它作为最高优先级业务流程规则执行。

---

当前 Skill：
{skill_name}

当前轮次：
{turn}/{MAX_SKILL_TURNS}

# Skill 权威规则
{policy}

---

# 用户问题
{user_input}

session_id:
{session_id}

---

# 当前 Skill 可调用 MCP（只能调用这些）
{tools_text}

---

# 已调用工具
{executed or "[]"}

说明：
- 已调用工具结果会出现在累计上下文中，格式为 [tool:名称]。
- status=ok 表示工具调用成功，但不代表业务流程已经完成。
- 不允许因为没有看到完整结果而重复调用同一个工具。
- 是否继续调用工具，必须依据 Skill 流程判断。

---

# 累计上下文
{context if context else "(空)"}

---

# 执行原则（必须遵守）

## 1. Skill 与 MCP 的关系

- Skill 是业务流程控制层。
- MCP 是底层数据获取和能力执行层。

必须：
- 先遵循 Skill 流程，再决定是否调用 MCP。
- MCP 只能用于满足 Skill 明确要求的数据获取或能力调用。

禁止：
- 绕过 Skill 流程直接调用 MCP 得出业务结论；
- 看到一个匹配工具就立即调用；
- 使用 MCP 返回结果替代 Skill 要求的分析步骤。

---

## 2. call_mcp 条件

只有以下情况允许 call_mcp：

- Skill 当前步骤明确要求获取某类数据；
- 当前上下文缺少完成下一步骤所需的信息；
- 该 MCP 在允许列表中。

调用时：
- 一次只能调用一个 MCP；
- purpose 必须说明调用目的；
- 不允许无目的探索。

---

## 3. analyze 条件

当：
- 已获得必要工具数据；
- Skill 要求进行分析、摘要、判断；

必须执行 analyze。

analyze 内容：
- 必须基于已有数据；
- 必须遵循 Skill 分析要求；
- 不超过1500字。

禁止：
- 没有数据时凭空分析；
- 跳过 Skill 要求的分析环节。

---

## 4. final_answer 条件

只有满足以下条件才能 final_answer：

- Skill要求的数据已经获取；
- 必需分析步骤已经完成；
- 不存在 Skill 明确要求的后续动作；
- 当前结果可以支撑最终报告。

注意：
final_answer 只表示结束执行流程。

不要在 user_message 中输出完整报告。
完整报告由系统根据 Skill 输出模板生成。

---

## 5. stop 条件

遇到以下情况必须 stop：

- 用户对象无法唯一确认；
- 必需参数缺失且无法从上下文推断；
- Skill要求用户确认；
- 工具返回空结果且 Skill 没有定义自动处理方式。

禁止：
- 猜测设备名称；
- 猜测机组；
- 猜测测点；
- 编造不存在的数据。

---

## 6. 防循环规则

如果：
- 某工具已经调用成功；
- 上下文已有满足当前步骤的数据；

下一步优先：
- analyze；
- final_answer。

禁止重复调用相同工具。

当接近最大轮次：
- 优先利用已有结果完成分析；
- 禁止无意义继续查询。

---

# 你的任务

根据 Skill 流程和当前状态，只决定下一步一个动作。

可选 action：

1. call_mcp
说明：
调用一个 MCP 获取 Skill 所需数据。

2. analyze
说明：
根据已有数据执行 Skill 要求的中间分析。

3. final_answer
说明：
流程完成，结束执行。

4. stop
说明：
需要用户补充信息或无法继续。

---

# 输出要求

只输出一个合法 JSON。

不要输出：
- markdown；
- 解释文字；
- 多个 JSON；
- steps；
- params 说明。

JSON 字段：

{{
  "action": "call_mcp|analyze|final_answer|stop",
  "reason": "说明依据 Skill 哪一步或哪条规则",
  "mcp": "仅 call_mcp 时填写，否则为空",
  "purpose": "仅 call_mcp 时填写调用目的，否则为空",
  "params": {{}},
  "content": "仅 analyze 时填写分析内容，否则为空",
  "user_message": "仅 final_answer 或 stop 时填写，否则为空"
}}

注意：
- content 和 user_message 中换行必须转义为 \\n；
- 双引号必须转义为 \\"；
- 保证 JSON 可以直接解析。
"""
    try:
        response = coordinator.llm_client.invoke(prompt, temperature=0.15, max_tokens=2500)
        data = parse_json(response)
        if isinstance(data, dict) and data.get("action"):
            return data
        logger.warning(
            "decide_skill_next_action: parsed but missing action, raw=%s",
            (response or "")[:300],
        )
    except Exception as e:
        logger.warning(
            "decide_skill_next_action failed: %s | raw_preview will retry compact",
            e,
        )
        # Compact retry: force short JSON only (avoids broken multi-line content)
        try:
            retry = f"""根据上下文只输出下一动作 JSON（合法 JSON，content 用 \\n，勿 markdown）：
skill={skill_name} turn={turn}
已调用={executed}
用户问题={user_input}
上下文摘要（截断）:
{(context or "")[:2500]}
可选 action: call_mcp|analyze|final_answer|stop
格式: {{"action":"...","reason":"...","mcp":"","content":"","user_message":""}}
"""
            response2 = coordinator.llm_client.invoke(retry, temperature=0.1, max_tokens=800)
            data2 = parse_json(response2)
            if isinstance(data2, dict) and data2.get("action"):
                return data2
        except Exception as e2:
            logger.warning("decide_skill_next_action retry failed: %s", e2)

    # If tools already ran, prefer analyze over hard stop so pipeline can continue
    if executed:
        return {
            "action": "analyze",
            "reason": "policy_json_parse_failed_fallback_analyze",
            "content": (
                "（系统提示：策略 JSON 解析失败，请基于已调用工具结果继续按 SKILL 输出"
                "初步分析摘要或最终结论所需结构。）"
            ),
        }
    return {
        "action": "stop",
        "reason": "policy_decide_failed",
        "user_message": "暂时无法按技能规范完成分析，请稍后重试或补充更具体的机组/设备名称。",
    }


def resolve_params_for_mcp(
    coordinator: Any,
    *,
    mcp_name: str,
    mcp_tools_cache: list,
    user_input: str,
    session_id: str,
    purpose: str = "",
    accumulated_results: str = "",
) -> Dict[str, Any]:
    """Before each step: skip AI if no params; else fill from cumulative context + tool schema."""
    tool = resolve_tool(mcp_name, mcp_tools_cache, coordinator)
    if tool is None:
        logger.warning("resolve_params_for_mcp: tool not found %s", mcp_name)
        return {}
    if not tool_needs_params(tool):
        logger.info("flash step: %s needs no params, call directly", mcp_name)
        return {}
    return resolve_step_params(
        coordinator,
        tool=tool,
        user_input=user_input,
        session_id=session_id,
        purpose=purpose,
        accumulated_results=accumulated_results,
    )


def _normalize_routed_skills(
    coordinator: Any,
    raw: Any,
    available_skills: Dict,
) -> List[str]:
    """Normalize router output to ordered skill name list."""
    items: List[Any] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, str) and raw.strip():
        items = [raw.strip()]

    threshold = coordinator.config.execution.confidence_threshold
    names: List[str] = []
    for item in items:
        name = None
        conf = 0.8
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("skill") or item.get("name")
            conf = float(item.get("confidence") or 0.8)
        if not name or name not in (available_skills or {}):
            if name:
                logger.warning("flash route: drop unknown skill %s", name)
            continue
        if conf < threshold:
            logger.info("flash route: drop skill %s confidence %.2f", name, conf)
            continue
        if name not in names:
            names.append(name)
    return names


def route_skills(
    coordinator: Any,
    user_input: str,
    available_skills: Dict,
    mcp_catalog: str = "",
    session_history: str = "",
) -> Dict[str, Any]:
    skills_desc_lines = []
    for name, skill in (available_skills or {}).items():
        desc = getattr(skill, "description", "") or ""
        triggers = getattr(skill, "triggers", None) or []
        skills_desc_lines.append(
            f"- {name}: {desc}"
            + (f" | triggers={triggers}" if triggers else "")
        )
    skills_desc = "\n".join(skills_desc_lines) if skills_desc_lines else "(no skills)"
    catalog_snip = mcp_catalog or ""
    history_snip = (session_history or "").strip()
    if len(history_snip) > 3000:
        history_snip = history_snip[:3000] + "\n...(history truncated)"

    prompt = f"""你是问答路径路由器；根据用户问题的业务意图选择最合适的处理路径。

路径选择原则：
- 优先选择能够完整满足用户业务需求的能力。
- skill 是面向业务场景的处理流程，包含意图理解、业务规则、结果组织等能力；
- mcp 是底层功能接口，提供具体的数据查询或工具执行能力。
- 如果已有 skill 能完整解决用户问题，应优先选择 skill，不要直接选择其底层依赖的 mcp。
- 如果没有匹配的 skill，但存在可直接满足用户需求的 mcp，则选择 mcp。
- 如果 skill 和 mcp 都可以满足需求，则比较专业性：
  - 面向具体业务场景、有明确分析流程的，优先 skill；
  - 仅需要调用单一工具获取数据或执行操作的，优先 mcp。
- 如果用户问题不需要业务数据、不涉及工具能力，则选择 direct。
- 若会话历史显示用户在追问同一业务对象，优先延续上一轮 path/skill。

用户问题：
{user_input}

会话历史（可空）：
{history_snip if history_snip else "(空)"}

可用 Skills（仅 path=skill 时才填 skills）：
{skills_desc}

可用 MCP 工具目录：
{catalog_snip or "(无)"}

规则：
1. path 三选一：
   - "skill"：用户问题匹配已有业务技能，skill 可以完整处理用户需求；skills 填匹配 skill，通常 0~1 个。
   - "mcp"：用户问题没有对应 skill，但可以通过某个 mcp 工具直接处理；skills 必须为 []。
   - "direct"：闲聊、概念解释、普通问答或不需要业务数据。
2. path=skill 时，只选择满足用户需求的最少 skill，如果存在强制前置 skill，必须同时加入；除强制前置 skill 外，业务 skill 通常不超过1个。。
3. path=mcp 或 path=direct 时，skills 必须为 []。
4. 不要因为某个 mcp 可以提供底层数据，就绕过已有 skill。
5. 不要输出 steps、params。只输出 JSON。

{{
  "intent": "用户意图简述",
  "path": "",
  "skills": [],
  "direct_answer": "仅 path=direct 时的简短指引（可空）"
}}
"""
    try:
        response = coordinator.llm_client.invoke(prompt, temperature=0.1, max_tokens=5000)
        data = parse_json(response)
        if not isinstance(data, dict):
            raise ValueError("route is not a dict")
        path = str(data.get("path") or "mcp").lower().strip()
        if path not in ("mcp", "skill", "direct"):
            path = "mcp"
        skills = _normalize_routed_skills(
            coordinator, data.get("skills"), available_skills
        )
        if path != "skill":
            skills = []
        elif not skills:
            path = "mcp"
        return {
            "intent": data.get("intent") or "",
            "path": path,
            "skills": skills,
            "direct_answer": data.get("direct_answer") or "",
        }
    except Exception as e:
        logger.warning("flash skill route failed: %s", e, exc_info=True)
        return {
            "intent": "route_failed",
            "path": "mcp",
            "skills": [],
            "direct_answer": f"请直接回答用户问题：{user_input}",
        }
