"""数据库管理"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.gateway.config import settings

# SQLAlchemy Base
Base = declarative_base()

# 全局引擎和会话
_engine = None
_async_session_maker = None


async def init_db():
    """初始化数据库"""
    global _engine, _async_session_maker

    # 转换 SQLite URL 为异步格式
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")

    _engine = create_async_engine(
        db_url,
        echo=settings.DEBUG,
        future=True
    )

    _async_session_maker = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

    # 确保模型已注册到 Base.metadata
    import app.gateway.models  # noqa: F401
    import agent.memory.long_term_memory  # noqa: F401
    import agent.memory.storage  # noqa: F401

    # 创建表
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """关闭数据库连接"""
    if _engine:
        await _engine.dispose()


async def get_session() -> AsyncSession:
    """获取数据库会话"""
    if _async_session_maker is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    async with _async_session_maker() as session:
        yield session
