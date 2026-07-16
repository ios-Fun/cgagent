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
from agent.config import Config
from agent.coordinator import Coordinator
from agent.memory.long_term_memory import get_long_term_memory_service
from psycopg import sql
from agent.sql.pgsql import execute_sql
router = APIRouter()


# 简化的内存存储（生产环境应使用数据库）
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
        session_id = str(uuid.uuid4())

    # 获取历史记录
    history = _chat_history.get(session_id, [])

    # 调用 Agent 框架处理
    try:
        ltm = get_long_term_memory_service()
        # 对话开始：加载用户画像并注入系统提示词（deerflow 风格）
        memory_context = ltm.build_injection_from_profile(user_id=request.user_id)
        memories = await ltm.retrieve_for_conversation(
            user_id=request.user_id,
            user_message=request.message,
            limit=10,
        )
        if not memory_context and memories:
            memory_context = ltm.build_system_memory_block(memories)

        coordinator = Coordinator.get_shared()

        result = await coordinator.process(
            session_id,
            request.message,
            user_id=request.user_id,
            memory_context=memory_context or None,
            mode=getattr(request, "mode", None) or "default",
        )

        # 异步更新画像（debounce 队列 + LLM，不阻塞主流程）
        turn_messages = history + [
            {"role": "user", "content": request.message},
            {"role": "assistant", "content": result.get("final_response", "")},
        ]
        ltm.enqueue_conversation(
            user_id=request.user_id,
            messages=turn_messages[-12:],
            session_id=session_id,
        )

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


        metrics = result.get("metrics") or {}
        metrics["long_term_memory_injected"] = bool(memory_context)
        metrics["memory_facts"] = len(memories)

        return ChatResponse(
            response=result["final_response"],
            session_id=session_id,
            success=result.get("success", True),
            metrics=metrics
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
            from agent.coordinator import Coordinator

            session_id = request.session_id or f"session_{uuid.uuid4().hex[:16]}"

            ltm = get_long_term_memory_service()
            memory_context = ltm.build_injection_from_profile(user_id=request.user_id)
            memories = await ltm.retrieve_for_conversation(
                user_id=request.user_id,
                user_message=request.message,
                limit=10,
            )
            if not memory_context and memories:
                memory_context = ltm.build_system_memory_block(memories)

            coordinator = Coordinator.get_shared()
            result = await coordinator.process(
                session_id,
                request.message,
                stream=True,
                user_id=request.user_id,
                memory_context=memory_context or None,
                mode=getattr(request, "mode", None) or "default",
            )

            ltm.enqueue_conversation(
                user_id=request.user_id,
                messages=[
                    {"role": "user", "content": request.message},
                    {"role": "assistant", "content": str(result.get("final_response", ""))},
                ],
                session_id=session_id,
            )

            final = result["final_response"]
            if hasattr(final, "__iter__") and not isinstance(final, str):
                for chunk in final:
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            else:
                yield f"data: {json.dumps({'chunk': final})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话信息"""
    query_sql = sql.SQL("select * from runs where session_id = {}::text").format(sql.Placeholder())

    result = execute_sql(query_sql, params= (session_id,), fetch=True)
    return result


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
