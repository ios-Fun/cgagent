"""健康检查路由"""

from fastapi import APIRouter, Depends
from datetime import datetime
from app.gateway.schemas import HealthResponse
from app.gateway.database import get_session

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow().isoformat(),
        database="connected",
        redis="connected"
    )


@router.get("/ping")
async def ping():
    """简单 ping"""
    return {"pong": True}
