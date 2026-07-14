import logging
from typing import Any, Dict

from langchain_core.tools import BaseTool

from agent.yaml_settings import get_section

logger = logging.getLogger(__name__)


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


async def get_mcp_tools() -> list[BaseTool]:
    logger.info("get_mcp_tools")
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
        return tools
    except Exception as e:
        logger.error("Failed to load MCP tools: %s", e, exc_info=True)
        return []
