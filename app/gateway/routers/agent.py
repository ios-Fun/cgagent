"""智能体对话路由"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from typing import Optional
import uuid
import json
from datetime import datetime

from app.gateway.schemas import ChatRequest, ChatResponse
from app.gateway.exceptions import SessionNotFoundException, InvalidRequestException
from app.gateway.models import Session, ChatHistory

router = APIRouter()


# 简化的内存存储（生产环境应使用数据库）
_sessions = {}
_chat_history = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    req: Request
):
    """处理对话请求"""
    tenant_id = getattr(req.state, "tenant_id", "default")

    # 获取或创建会话
    session_id = request.session_id
    if not session_id:
        session_id = f"session_{uuid.uuid4().hex[:16]}"

    # 获取历史记录
    history = _chat_history.get(session_id, [])

    # 调用 Agent 框架处理
    try:
        # 这里集成实际的 Agent Framework
        from agent.config import Config
        from agent.coordinator import Coordinator

        # 加载配置
        config = Config.from_file()
        coordinator = Coordinator(config)

        # 处理请求
        result = coordinator.process(request.message)

        # 保存历史
        history.append({
            "role": "user",
            "content": request.message,
            "timestamp": datetime.utcnow().isoformat()
        })
        history.append({
            "role": "assistant",
            "content": result["final_response"],
            "timestamp": datetime.utcnow().isoformat()
        })
        _chat_history[session_id] = history

        # 保存会话
        _sessions[session_id] = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_id": request.user_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_active": datetime.utcnow().isoformat()
        }

        return ChatResponse(
            response=result["final_response"],
            session_id=session_id,
            success=result.get("success", True),
            metrics=result.get("metrics")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    req: Request
):
    """流式对话"""
    tenant_id = getattr(req.state, "tenant_id", "default")

    async def generate():
        """生成流式响应"""
        try:
            from agent.config import Config
            from agent.coordinator import Coordinator

            config = Config.from_file()
            coordinator = Coordinator(config)

            # 流式处理
            result = coordinator.process(request.message, stream=True)

            if hasattr(result["final_response"], "__iter__"):
                for chunk in result["final_response"]:
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            else:
                yield f"data: {json.dumps({'chunk': result['final_response']})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话信息"""
    session = _sessions.get(session_id)
    if not session:
        raise SessionNotFoundException(session_id)
    return session


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str):
    """获取会话历史"""
    history = _chat_history.get(session_id, [])
    return {
        "session_id": session_id,
        "messages": history,
        "total": len(history)
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if session_id in _sessions:
        del _sessions[session_id]
    if session_id in _chat_history:
        del _chat_history[session_id]
    return {"deleted": True}
