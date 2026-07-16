import json
import logging

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from app.gateway.database import init_db, close_db
from app.gateway.config import settings
from app.gateway.routers import agent, skills, health, memory
# from deerflow.config.extensions_config import ExtensionsConfig, get_extensions_config, reload_extensions_config
# from deerflow.config import app_config as deerflow_app_config
# get_app_config = deerflow_app_config.get_app_config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    logging.getLogger("backend").setLevel(logging.INFO)
    # 启动时初始化
    logger.info("🚀 Agent Framework API 启动中...")
    await init_db()
    logger.info("✅ 数据库初始化完成")

    from agent.memory.long_term_memory import get_long_term_memory_service
    ltm = get_long_term_memory_service()
    await ltm.start()
    logger.info("✅ 长期记忆服务已启动")

    try:
        from agent.coordinator import Coordinator
        from agent.mcp.mcptools import get_mcp_tools

        Coordinator.get_shared()
        tools = await get_mcp_tools()
        logger.info("✅ MCP tools 预加载完成: %d tool(s)", len(tools))
    except Exception as e:
        logger.warning("⚠️ MCP/Coordinator 预加载失败（请求时将重试）: %s", e)

    logger.info("🌐 API 服务已启动")

    yield
    # 关闭时清理
    logger.info("🛑 Agent Framework API 关闭中...")
    from agent.memory.long_term_memory import get_long_term_memory_service
    await get_long_term_memory_service().stop()
    try:
        from agent.mcp.mcptools import reset_mcp_tools_cache
        from agent.coordinator import Coordinator

        reset_mcp_tools_cache()
        Coordinator.reset_shared()
    except Exception:
        pass
    await close_db()
    logger.info("✅ 清理完成")

def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Framework API",
        description="通用智能体开发框架 - REST API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(health.router, prefix="/api/v1", tags=["健康检查"])
    app.include_router(agent.router, prefix="/api/v1/agent", tags=["智能体对话"])
    app.include_router(skills.router, prefix="/api/v1/skills", tags=["技能管理"])
    app.include_router(memory.router, prefix="/api/v1/memory", tags=["长期记忆"])

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """Health check endpoint.

        Returns:
            Service health status information.
        """
        return {"status": "healthy", "service": "deer-flow-gateway"}

    return app

# Create app instance for uvicorn
app = create_app()
