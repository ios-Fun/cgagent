"""长期记忆查询 / 管理路由。"""
"""
GET	/api/v1/memory/status	配置状态
GET	/api/v1/memory/users/{user_id}	完整画像 + 注入预览
GET	/api/v1/memory/users/{user_id}/facts	facts 列表（可按 category）
GET	/api/v1/memory/users/{user_id}/search?q=	关键词检索
POST	/api/v1/memory/users/{user_id}/facts	手动新增 fact
DELETE	/api/v1/memory/users/{user_id}/facts/{fact_id}	删单条
DELETE	/api/v1/memory/users/{user_id}	清空画像
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.memory.config import get_memory_config
from agent.memory.long_term_memory import get_long_term_memory_service
from agent.memory.prompt import format_memory_for_injection
from agent.memory.updater import (
    clear_memory_data,
    create_memory_fact,
    delete_memory_fact,
    get_memory_data,
    reload_memory_data,
)

router = APIRouter()


class MemoryFactCreateRequest(BaseModel):
    content: str = Field(..., description="事实内容")
    category: str = Field("context", description="preference|knowledge|context|behavior|goal|correction")
    confidence: float = Field(0.9, ge=0.0, le=1.0)
    agent_name: Optional[str] = Field(None, description="可选 agent 作用域")


class MemoryProfileResponse(BaseModel):
    user_id: str
    agent_name: Optional[str] = None
    memory: Dict[str, Any]
    fact_count: int
    injection_preview: Optional[str] = None


class MemoryFactsResponse(BaseModel):
    user_id: str
    agent_name: Optional[str] = None
    facts: List[Dict[str, Any]]
    total: int


class MemorySearchResponse(BaseModel):
    user_id: str
    query: Optional[str] = None
    profile_facts: List[Dict[str, Any]]
    flat_memories: List[Dict[str, Any]]
    total: int


class MemoryStatusResponse(BaseModel):
    enabled: bool
    injection_enabled: bool
    use_llm_update: bool
    debounce_seconds: int
    max_facts: int
    fact_confidence_threshold: float


@router.get("/status", response_model=MemoryStatusResponse)
async def memory_status():
    """记忆模块配置状态。"""
    cfg = get_memory_config()
    return MemoryStatusResponse(
        enabled=cfg.enabled,
        injection_enabled=cfg.injection_enabled,
        use_llm_update=cfg.use_llm_update,
        debounce_seconds=cfg.debounce_seconds,
        max_facts=cfg.max_facts,
        fact_confidence_threshold=cfg.fact_confidence_threshold,
    )


@router.get("/users/{user_id}", response_model=MemoryProfileResponse)
async def get_user_memory(
    user_id: str,
    agent_name: Optional[str] = Query(None, description="可选 agent 作用域"),
    include_injection: bool = Query(True, description="是否返回注入预览文本"),
    reload: bool = Query(False, description="是否强制从 SQLite 重载（绕过缓存）"),
):
    """查询用户完整记忆画像（user / history / facts）。"""
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    if reload:
        memory = reload_memory_data(agent_name, user_id=user_id)
    else:
        memory = get_memory_data(agent_name, user_id=user_id)

    facts = memory.get("facts") or []
    injection = None
    if include_injection:
        cfg = get_memory_config()
        injection = format_memory_for_injection(
            memory,
            max_tokens=cfg.max_injection_tokens,
            guaranteed_categories=cfg.guaranteed_categories,
            guaranteed_token_budget=cfg.guaranteed_token_budget,
        ) or None

    return MemoryProfileResponse(
        user_id=user_id,
        agent_name=agent_name,
        memory=memory,
        fact_count=len(facts),
        injection_preview=injection,
    )


@router.get("/users/{user_id}/facts", response_model=MemoryFactsResponse)
async def list_user_facts(
    user_id: str,
    agent_name: Optional[str] = Query(None),
    category: Optional[str] = Query(None, description="按 category 过滤"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """列出用户 facts。"""
    memory = get_memory_data(agent_name, user_id=user_id)
    facts = memory.get("facts") or []
    filtered = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        if category and (f.get("category") or "") != category:
            continue
        try:
            conf = float(f.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < min_confidence:
            continue
        filtered.append(f)

    filtered.sort(key=lambda x: float(x.get("confidence") or 0), reverse=True)
    return MemoryFactsResponse(
        user_id=user_id,
        agent_name=agent_name,
        facts=filtered,
        total=len(filtered),
    )


@router.get("/users/{user_id}/search", response_model=MemorySearchResponse)
async def search_user_memory(
    user_id: str,
    q: str = Query(..., min_length=1, description="检索关键词/问题"),
    limit: int = Query(10, ge=1, le=50),
):
    """按关键词检索画像 facts + 扁平记忆表。"""
    ltm = get_long_term_memory_service()
    profile_facts = await ltm.retrieve_for_conversation(user_id=user_id, user_message=q, limit=limit)
    flat = await ltm.store.search(user_id=user_id, query=q, limit=limit)
    return MemorySearchResponse(
        user_id=user_id,
        query=q,
        profile_facts=profile_facts,
        flat_memories=flat,
        total=len(profile_facts) + len(flat),
    )


@router.post("/users/{user_id}/facts")
async def add_user_fact(user_id: str, body: MemoryFactCreateRequest):
    """手动新增一条 fact。"""
    try:
        memory = create_memory_fact(
            content=body.content,
            category=body.category,
            confidence=body.confidence,
            agent_name=body.agent_name,
            user_id=user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 同步扁平表，便于关键词检索
    ltm = get_long_term_memory_service()
    cat_to_type = {
        "preference": "preference",
        "knowledge": "fact",
        "context": "background",
        "behavior": "fact",
        "goal": "fact",
        "correction": "fact",
    }
    await ltm.save_explicit(
        user_id=user_id,
        content=body.content,
        memory_type=cat_to_type.get(body.category, "fact"),
        importance=max(1, min(5, int(body.confidence * 5))),
    )

    facts = memory.get("facts") or []
    return {
        "user_id": user_id,
        "success": True,
        "fact_count": len(facts),
        "latest": facts[-1] if facts else None,
    }


@router.delete("/users/{user_id}/facts/{fact_id}")
async def remove_user_fact(
    user_id: str,
    fact_id: str,
    agent_name: Optional[str] = Query(None),
):
    """删除指定 fact。"""
    try:
        memory = delete_memory_fact(fact_id, agent_name, user_id=user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"fact not found: {fact_id}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "user_id": user_id,
        "deleted_fact_id": fact_id,
        "fact_count": len(memory.get("facts") or []),
        "success": True,
    }


@router.delete("/users/{user_id}")
async def clear_user_memory(
    user_id: str,
    agent_name: Optional[str] = Query(None),
):
    """清空用户全部记忆画像。"""
    try:
        memory = clear_memory_data(agent_name, user_id=user_id)
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "user_id": user_id,
        "agent_name": agent_name,
        "cleared": True,
        "memory": memory,
    }
