import logging
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

async def get_mcp_tools() -> list[BaseTool]:
    logger.info("get_mcp_tools")
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed. Install it to enable MCP tools: pip install langchain-mcp-adapters")
        return []
    try:
        logger.info("get_mcp_tools2")
        client = MultiServerMCPClient(
            connections={
                "mcp-device-sse": {
                    "transport": "sse",
                    "url": "http://192.168.0.58:8084/sse"
                }
            }
        )
        tools = await client.get_tools()
        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")
        return tools

    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}", exc_info=True)
        return []