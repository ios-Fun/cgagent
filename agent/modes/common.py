"""Shared helpers for execution modes (deer-flow style tool invoke)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def format_mcp_catalog(mcp_tools_cache: list) -> str:
    """Format available MCP tools for the planner prompt (with arg types)."""
    lines = []
    for tool in mcp_tools_cache or []:
        name = getattr(tool, "name", str(tool))
        desc = (getattr(tool, "description", None) or "")[:200]
        args_desc = format_tool_args_for_prompt(tool)
        lines.append(f"- {name}: {desc}\n  args: {args_desc}")
    return "\n".join(lines) if lines else "(no MCP tools loaded)"


def skill_default_steps(skill: Any) -> List[Dict[str, Any]]:
    """Build default MCP steps from skill.tools order (fallback)."""
    steps = []
    for mcp in (getattr(skill, "tools", None) or []):
        steps.append({"mcp": mcp, "purpose": f"from skill {skill.name}", "params": {}})
    return steps


def _strip_code_fence(text: str) -> str:
    raw = (text or "").strip()
    if "```" not in raw:
        return raw
    # Prefer fenced block content
    parts = raw.split("```")
    # parts: [pre, lang?\nbody, after, ...]
    if len(parts) >= 3:
        body = parts[1]
        if "\n" in body:
            first, rest = body.split("\n", 1)
            if first.strip().lower() in ("json", "javascript", "js", ""):
                body = rest
        return body.strip()
    return raw


def _extract_json_slice(raw: str) -> str:
    start_obj = raw.find("{")
    start_arr = raw.find("[")
    if start_obj < 0 and start_arr < 0:
        return raw
    if start_obj < 0:
        start = start_arr
        open_c, close_c = "[", "]"
    elif start_arr < 0:
        start = start_obj
        open_c, close_c = "{", "}"
    else:
        if start_obj < start_arr:
            start = start_obj
            open_c, close_c = "{", "}"
        else:
            start = start_arr
            open_c, close_c = "[", "]"
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == open_c:
            depth += 1
        elif ch == close_c:
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    return raw[start:]


def _repair_json_newlines_in_strings(s: str) -> str:
    """Escape raw newlines/tabs inside JSON string literals (common LLM mistake)."""
    out: List[str] = []
    in_str = False
    escape = False
    for ch in s:
        if in_str:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                continue
            if ch == '"':
                out.append(ch)
                in_str = False
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_str = True
    return "".join(out)


def parse_json(text: str) -> Any:
    """Extract JSON object/array from LLM text (tolerant of fences / bad newlines)."""
    raw = _strip_code_fence(text)
    candidates = [raw]
    sliced = _extract_json_slice(raw)
    if sliced not in candidates:
        candidates.append(sliced)
    repaired = _repair_json_newlines_in_strings(sliced)
    if repaired not in candidates:
        candidates.append(repaired)

    last_err: Optional[Exception] = None
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = e
            continue
    # Last resort: regex extract action + key fields for policy decisions
    extracted = _loose_policy_fields(raw)
    if extracted:
        return extracted
    if last_err:
        raise last_err
    raise json.JSONDecodeError("Unable to parse JSON", raw, 0)


def _loose_policy_fields(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort extract policy action fields when full JSON is broken."""
    import re

    if not text:
        return None
    m = re.search(
        r'"action"\s*:\s*"(call_mcp|analyze|final_answer|stop|done)"',
        text,
        re.I,
    )
    if not m:
        return None
    action = m.group(1).lower()
    out: Dict[str, Any] = {"action": action, "reason": "loose_json_parse"}

    def _field(name: str) -> Optional[str]:
        # single-line string field
        mm = re.search(rf'"{name}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
        if mm:
            try:
                return json.loads(f'"{mm.group(1)}"')
            except Exception:
                return mm.group(1)
        return None

    for key in ("mcp", "tool", "purpose", "reason", "user_message", "content", "analysis"):
        val = _field(key)
        if val is not None:
            out[key] = val
    return out


def normalize_tool_name(name: str) -> str:
    """Normalize tool id for matching (strip common server prefixes)."""
    n = (name or "").strip()
    if not n:
        return ""
    # mcp server prefix: mcp-device-sse_unit_tags_realtime -> unit_tags_realtime
    if "_" in n and (n.startswith("mcp-") or n.startswith("mcp_")):
        # keep last segment after first underscore group carefully:
        # "mcp-device-sse_unit_tags_realtime" -> split once on first '_' after prefix-ish
        parts = n.split("_", 1)
        if len(parts) == 2 and parts[0].startswith("mcp"):
            return parts[1]
    return n


def tool_name_matches(declared: str, real: str) -> bool:
    """True if SKILL-declared name matches a loaded MCP tool name."""
    d = (declared or "").strip()
    r = (real or "").strip()
    if not d or not r:
        return False
    if d == r:
        return True
    dn = normalize_tool_name(d)
    rn = normalize_tool_name(r)
    if dn == rn:
        return True
    # suffix / prefix forms: unit_tags_realtime vs xxx_unit_tags_realtime
    if d.endswith(r) or r.endswith(d) or dn.endswith(rn) or rn.endswith(dn):
        return True
    # contains as whole token (avoid short false positives)
    if len(dn) >= 4 and (dn in r or dn in rn):
        return True
    if len(rn) >= 4 and (rn in d or rn in dn):
        return True
    return False


def resolve_tool(mcp_name: str, tools: list, coordinator: Any = None) -> Any:
    """Resolve a tool by name against mcp_tools_cache (exact / normalized / suffix)."""
    if not mcp_name:
        return None
    # Prefer direct match against cache names (authoritative)
    for tool in tools or []:
        name = getattr(tool, "name", None)
        if name and tool_name_matches(mcp_name, name):
            return tool
    # Optional coordinator helper as fallback
    if coordinator is not None and hasattr(coordinator, "find_mcp"):
        found = coordinator.find_mcp(mcp_name, tools)
        if found is not None:
            return found
    return None


def get_tool_input_schema(tool: Any) -> Dict[str, Any]:
    """Return JSON-schema properties map for a LangChain tool, if available."""
    # tool.args is often {name: property_schema}
    args = getattr(tool, "args", None)
    if isinstance(args, dict) and args:
        # values may already be property schemas
        if any(isinstance(v, dict) for v in args.values()):
            return args

    schema = getattr(tool, "args_schema", None)
    if schema is not None:
        try:
            if hasattr(schema, "model_json_schema"):
                js = schema.model_json_schema()
            elif hasattr(schema, "schema"):
                js = schema.schema()
            else:
                js = None
            if isinstance(js, dict):
                props = js.get("properties") or {}
                if isinstance(props, dict):
                    return props
        except Exception:
            pass
    return {}


def get_tool_arg_names(tool: Any) -> List[str]:
    """Return input argument names from a LangChain BaseTool."""
    props = get_tool_input_schema(tool)
    if props:
        return list(props.keys())
    return []


def _json_type_label(prop: Any) -> str:
    """Human-readable type label from a JSON-schema property."""
    if not isinstance(prop, dict):
        return "any"
    if "anyOf" in prop or "oneOf" in prop:
        variants = prop.get("anyOf") or prop.get("oneOf") or []
        labels = []
        for v in variants:
            if isinstance(v, dict):
                if v.get("type") == "null":
                    labels.append("null")
                else:
                    labels.append(_json_type_label(v))
        labels = [x for x in labels if x]
        return "|".join(labels) if labels else "any"
    t = prop.get("type")
    if isinstance(t, list):
        return "|".join(str(x) for x in t)
    if t == "array":
        items = prop.get("items") or {}
        item_t = items.get("type", "any") if isinstance(items, dict) else "any"
        return f"array[{item_t}]"
    if t:
        return str(t)
    return "any"


def get_tool_required_args(tool: Any) -> List[str]:
    """Return required argument names for a tool schema."""
    schema = getattr(tool, "args_schema", None)
    if schema is not None:
        try:
            if hasattr(schema, "model_json_schema"):
                js = schema.model_json_schema()
            elif hasattr(schema, "schema"):
                js = schema.schema()
            else:
                js = {}
            req = js.get("required") or []
            if isinstance(req, list):
                return [str(x) for x in req]
        except Exception:
            pass
    return []


def tool_needs_params(tool: Any) -> bool:
    """True if tool declares any input parameters (need AI fill or empty call)."""
    props = get_tool_input_schema(tool)
    return bool(props)


def format_tool_args_for_prompt(tool: Any) -> str:
    """Format tool args with types for planner prompts, e.g. num:string?, closed:boolean?."""
    props = get_tool_input_schema(tool)
    if not props:
        return "(no schema / no params)"

    required = set(get_tool_required_args(tool))
    parts = []
    for name, prop in props.items():
        label = _json_type_label(prop)
        opt = "" if name in required else "?"
        desc = ""
        if isinstance(prop, dict) and prop.get("description"):
            desc = f" ({str(prop['description'])[:80]})"
        parts.append(f"{name}:{label}{opt}{desc}")
    return ", ".join(parts)


def format_tool_detail_for_prompt(tool: Any) -> str:
    """Detailed single-tool description for step param filling."""
    name = getattr(tool, "name", str(tool))
    desc = (getattr(tool, "description", None) or "")[:400]
    args_desc = format_tool_args_for_prompt(tool)
    required = get_tool_required_args(tool)
    return (
        f"tool: {name}\n"
        f"description: {desc}\n"
        f"args: {args_desc}\n"
        f"required: {required or '[]'}"
    )


def resolve_step_params(
    coordinator: Any,
    *,
    tool: Any,
    user_input: str,
    session_id: str,
    purpose: str = "",
    accumulated_results: str = "",
) -> Dict[str, Any]:
    """Fill tool params via AI from cumulative context + tool schema.

    - If tool has no input schema: return {} (no need to ask).
    - Else: LLM returns JSON params matching schema types.
    """
    if not tool_needs_params(tool):
        logger.info(
            "resolve_step_params: tool %s has no params, skip AI",
            getattr(tool, "name", tool),
        )
        return {}

    tool_detail = format_tool_detail_for_prompt(tool)
    context = (accumulated_results or "").strip()
    if len(context) > 8000:
        context = context[:8000] + "\n...(truncated)"

    now = datetime.now().astimezone()
    now_iso = now.isoformat(timespec="seconds")
    now_human = now.strftime("%Y-%m-%d %H:%M:%S %z")

    prompt = f"""你是 MCP 工具参数填充器。

根据用户问题、已有上下文和当前 MCP schema，生成本次工具调用参数。

你只负责生成参数，不回答用户问题，不解释调用过程。

用户问题：
{user_input}

当前时间（计算相对时间唯一依据）：
ISO: {now_iso}
本地: {now_human}

调用目的：
{purpose or "(无)"}

已有上下文：
{context if context else "(空)"}

当前 MCP：
{tool_detail}

规则：
1. 只输出一个合法 JSON 对象，不要 markdown，不要解释。
2. 输出字段必须来自 MCP schema，禁止新增字段。
3. 参数类型必须严格匹配 schema：
   - string 用字符串；
   - integer 用数字；
   - boolean 用 true/false；
   - array 用数组。
    4. 参数来源优先级：
   - 已有上下文（含会话历史、前序 tool 结果）；
   - 用户明确提供的信息（含追问中的指代，需从会话历史还原测点/设备/编码等）；
   - Skill 已确认信息。
 5. 若用户问题是「查看所有/再查一次/刚才那个」等指代，必须从「已有上下文/会话历史」继承业务对象参数，不要留空。
 6. 禁止臆造关键业务信息：
   - 不猜 unit_id、device_id、tag_id、incident_id 等；
   - 不编造设备、机组、测点名称；
   - 但历史中已出现的编码/名称可直接复用。
 7. required 参数必须填写；如果当前句与历史都无法确定，不要猜测。
 8. optional 参数没有依据可以省略，不填 null。
 9. 使用 start_time/end_time 时，格式为 ISO 8601。
 10. 如果工具无需参数，输出 {{}}。
 11. 一次只生成当前 MCP 调用参数。

输出示例：
{{"unit_name":"京燃","start_time":"2026-01-01T00:00:00Z","end_time":"2026-01-02T00:00:00Z"}}
"""
    try:
        response = coordinator.llm_client.invoke(prompt, temperature=0.1, max_tokens=1024)
        data = parse_json(response)
        if isinstance(data, dict):
            # drop nulls
            params = {k: v for k, v in data.items() if v is not None}
            logger.info(
                "resolve_step_params: tool=%s keys=%s",
                getattr(tool, "name", ""),
                list(params.keys()),
            )
            return params
        logger.warning("resolve_step_params: non-dict response for %s", getattr(tool, "name", ""))
        return {}
    except Exception as e:
        logger.warning("resolve_step_params failed: %s", e, exc_info=True)
        return {}


def normalize_tool_result(result: Any) -> str:
    """Normalize tool return value to plain text (deer-flow / LangChain content)."""
    if result is None:
        return ""

    # content_and_artifact: (content, artifact)
    if isinstance(result, tuple) and len(result) >= 1:
        return normalize_tool_result(result[0])

    # ToolMessage
    content = getattr(result, "content", None)
    if content is not None and not isinstance(result, (str, dict, list)):
        return normalize_tool_result(content)

    if isinstance(result, list):
        parts: List[str] = []
        for item in result:
            if isinstance(item, dict):
                # LangChain content blocks: {"type":"text","text":"..."}
                if item.get("type") == "text" and item.get("text") is not None:
                    parts.append(str(item["text"]))
                elif item.get("text") is not None:
                    parts.append(str(item["text"]))
                elif item.get("content") is not None:
                    parts.append(str(item["content"]))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)

    if isinstance(result, dict):
        if result.get("type") == "text" and result.get("text") is not None:
            return str(result["text"])
        if result.get("text") is not None:
            return str(result["text"])
        if result.get("content") is not None:
            return normalize_tool_result(result["content"])
        return json.dumps(result, ensure_ascii=False)

    return str(result)


async def invoke_mcp(
    coordinator: Any,
    session_id: str,
    user_input: str,
    mcp_name: str,
    mcp_tools_cache: list,
    params_hint: Optional[Dict[str, Any]] = None,
) -> str:
    """Invoke MCP tool like deer-flow: use caller-provided args only, then ainvoke.

    deer-flow path:
      LLM tool_call.args  ->  tool.ainvoke(args)  ->  content text
    Here:
      params_hint (from plan / extra decide)  ->  tool.ainvoke(args)  ->  text
    No Redis / special-case param filling.
    """
    tool = resolve_tool(mcp_name, mcp_tools_cache, coordinator)
    if tool is None:
        logger.warning("MCP tool not found: %s", mcp_name)
        # Do not leak internal tool names/errors to the user-facing synthesis path
        return ""

    # Only explicit args from planner/decider (same role as tool_call["args"])
    arguments: Dict[str, Any] = {}
    if isinstance(params_hint, dict):
        arguments = {k: v for k, v in params_hint.items() if v is not None}

    tool_name = getattr(tool, "name", mcp_name)
    logger.info("invoke MCP name=%s args=%s", tool_name, list(arguments.keys()))

    try:
        # LangChain BaseTool / StructuredTool
        raw = await tool.ainvoke(arguments)
        text = normalize_tool_result(raw)
        if _looks_like_tool_error(text):
            logger.warning(
                "MCP returned error-like payload name=%s snippet=%s",
                tool_name,
                (text or "")[:300],
            )
            return ""
        logger.info("invoke MCP ok name=%s result_len=%d", tool_name, len(text or ""))
        return text or ""
    except Exception as e:
        # Log full detail; never pass stack/validation text into synthesis context
        logger.exception("Tool execution failed: name=%s err=%s", tool_name, e)
        return ""


def _looks_like_tool_error(text: str) -> bool:
    """Heuristic: tool/validation dumps should not go to the user synthesis path."""
    if not text:
        return False
    s = text.lower()
    markers = (
        "validation error",
        "pydantic",
        "string_type",
        "list_type",
        "bool_type",
        "input should be",
        "field required",
        "toolexception",
        "traceback",
        "mcp 调用失败",
        "call_tool",
        "type_error",
    )
    return any(m in s for m in markers)
