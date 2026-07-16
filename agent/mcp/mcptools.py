"""MCP tools loader with process-level cache (avoid reconnect every request)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool

from agent.yaml_settings import get_section

logger = logging.getLogger(__name__)

# Process-level cache (deer-flow style)
_mcp_tools_cache: Optional[List[BaseTool]] = None
_cache_initialized: bool = False
_cache_ts: float = 0.0
_init_lock = asyncio.Lock()
# Optional TTL (seconds); 0 = never expire until process restart / reset
_CACHE_TTL_SECONDS = 0


def _default_connections() -> Dict[str, Any]:
    return {
        "mcp-device-sse": {
            "transport": "sse",
            "url": "http://192.168.0.44:8084/sse",
        }
    }


def get_mcp_connections() -> Dict[str, Any]:
    """从 config.yaml 的 mcp.servers 读取 MCP 连接配置。"""
    mcp_cfg = get_section("mcp")
    servers = mcp_cfg.get("servers")
    if isinstance(servers, dict) and servers:
        return servers
    return _default_connections()


def reset_mcp_tools_cache() -> None:
    """Clear cached tools (e.g. after MCP server list changes)."""
    global _mcp_tools_cache, _cache_initialized, _cache_ts
    _mcp_tools_cache = None
    _cache_initialized = False
    _cache_ts = 0.0
    logger.info("MCP tools cache reset")


def _cache_is_valid() -> bool:
    if not _cache_initialized or _mcp_tools_cache is None:
        return False
    if _CACHE_TTL_SECONDS and _CACHE_TTL_SECONDS > 0:
        if time.time() - _cache_ts > _CACHE_TTL_SECONDS:
            return False
    return True


async def _load_mcp_tools() -> list[BaseTool]:
    """Connect to MCP servers and list tools (slow network path)."""
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning(
            "langchain-mcp-adapters not installed. "
            "Install it to enable MCP tools: pip install langchain-mcp-adapters"
        )
        return []
    try:
        connections = get_mcp_connections()
        logger.info("MCP connections: %s", list(connections.keys()))
        client = MultiServerMCPClient(connections=connections)
        tools = await client.get_tools()
        logger.info("Successfully loaded %d tool(s) from MCP servers", len(tools))
        return list(tools or [])
    except Exception as e:
        logger.error("Failed to load MCP tools: %s", e, exc_info=True)
        return []


async def get_mcp_tools(*, force_reload: bool = False) -> list[BaseTool]:
    """Get MCP tools, reusing process cache after first load.

    Why it was slow without cache:
      Each call created MultiServerMCPClient and ran get_tools():
      TCP/SSE connect + MCP handshake + tools/list over the network.
      flash called this every request → multi-second delay each time.

    Args:
        force_reload: Bypass cache and reconnect.
    """
    global _mcp_tools_cache, _cache_initialized, _cache_ts

    if not force_reload and _cache_is_valid():
        logger.debug("MCP tools cache hit: %d tool(s)", len(_mcp_tools_cache or []))
        return list(_mcp_tools_cache or [])

    async with _init_lock:
        # Double-check after lock (concurrent first requests)
        if not force_reload and _cache_is_valid():
            return list(_mcp_tools_cache or [])

        logger.info("get_mcp_tools: loading from servers (cache miss)...")
        t0 = time.perf_counter()
        tools = await _load_mcp_tools()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _mcp_tools_cache = tools
        _cache_initialized = True
        _cache_ts = time.time()
        logger.info(
            "get_mcp_tools: cached %d tool(s) in %.0fms",
            len(tools),
            elapsed_ms,
        )
        return list(tools)
