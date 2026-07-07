"""
短期工作记忆

管理当前会话的对话历史、上下文状态和关键信息
"""

import time
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Callable, Set
from datetime import datetime
from collections import deque


@dataclass
class ConversationTurn:
    """对话轮次"""
    turn_id: int
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    intent: Optional[str] = None
    extracted_slots: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "intent": self.intent,
            "extracted_slots": self.extracted_slots,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        """从字典创建"""
        return cls(
            turn_id=data["turn_id"],
            role=data["role"],
            content=data["content"],
            timestamp=data.get("timestamp", time.time()),
            intent=data.get("intent"),
            extracted_slots=data.get("extracted_slots", {}),
            metadata=data.get("metadata", {})
        )


@dataclass
class ConversationContext:
    """对话上下文"""
    session_id: str
    user_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    turns: List[ConversationTurn] = field(default_factory=list)

    # 提取的关键信息
    current_topic: Optional[str] = None
    current_intent: Optional[str] = None
    pending_slots: Dict[str, Any] = field(default_factory=dict)
    confirmed_info: Dict[str, Any] = field(default_factory=dict)

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, role: str, content: str, **kwargs) -> ConversationTurn:
        """添加对话轮次"""
        turn_id = len(self.turns)
        turn = ConversationTurn(
            turn_id=turn_id,
            role=role,
            content=content,
            **kwargs
        )
        self.turns.append(turn)
        self.last_activity = time.time()
        return turn

    def get_recent_turns(self, n: int = 5, role: Optional[str] = None) -> List[ConversationTurn]:
        """获取最近的对话轮次"""
        turns = self.turns
        if role:
            turns = [t for t in turns if t.role == role]
        return turns[-n:] if len(turns) > n else turns

    def get_user_messages(self, n: int = 10) -> List[str]:
        """获取用户消息列表"""
        turns = [t for t in self.turns if t.role == "user"]
        return [t.content for t in (turns[-n:] if len(turns) > n else turns)]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "start_time": self.start_time,
            "last_activity": self.last_activity,
            "turns": [t.to_dict() for t in self.turns],
            "current_topic": self.current_topic,
            "current_intent": self.current_intent,
            "pending_slots": self.pending_slots,
            "confirmed_info": self.confirmed_info,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        """从字典创建"""
        ctx = cls(
            session_id=data["session_id"],
            user_id=data.get("user_id"),
            start_time=data.get("start_time", time.time()),
            last_activity=data.get("last_activity", time.time()),
            current_topic=data.get("current_topic"),
            current_intent=data.get("current_intent"),
            pending_slots=data.get("pending_slots", {}),
            confirmed_info=data.get("confirmed_info", {}),
            metadata=data.get("metadata", {})
        )
        ctx.turns = [ConversationTurn.from_dict(t) for t in data.get("turns", [])]
        return ctx


class WorkingMemory:
    """
    短期工作记忆

    管理当前会话的对话历史、上下文状态和关键信息
    """

    def __init__(self, session_id: Optional[str] = None,
                 max_history: int = 100,
                 context_ttl: int = 3600):
        self.session_id = session_id or self._generate_session_id()
        self.max_history = max_history
        self.context_ttl = context_ttl

        # 对话上下文
        self._context: Optional[ConversationContext] = None

        # 信息提取回调
        self._extractors: List[Callable[[str], Dict[str, Any]]] = []

        # 初始化上下文
        self._init_context()

    def _generate_session_id(self) -> str:
        """生成会话ID"""
        return f"sess_{uuid.uuid4().hex[:16]}"

    def _init_context(self):
        """初始化对话上下文"""
        self._context = ConversationContext(session_id=self.session_id)

    @property
    def context(self) -> ConversationContext:
        """获取对话上下文"""
        if self._context is None:
            self._init_context()
        return self._context

    def add_user_message(self, content: str, **kwargs) -> ConversationTurn:
        """添加用户消息"""
        turn = self.context.add_turn("user", content, **kwargs)

        # 信息提取
        self._extract_information(content)

        # 限制历史长度
        self._trim_history()

        return turn

    def add_assistant_message(self, content: str, **kwargs) -> ConversationTurn:
        """添加助手消息"""
        return self.context.add_turn("assistant", content, **kwargs)

    def add_system_message(self, content: str, **kwargs) -> ConversationTurn:
        """添加系统消息"""
        return self.context.add_turn("system", content, **kwargs)

    def get_history(self, n: int = 10) -> List[ConversationTurn]:
        """获取最近的对话历史"""
        return self.context.get_recent_turns(n)

    def get_user_messages(self, n: int = 5) -> List[str]:
        """获取用户消息列表"""
        return self.context.get_user_messages(n)

    def set_current_intent(self, intent: str):
        """设置当前意图"""
        self.context.current_intent = intent

    def set_current_topic(self, topic: str):
        """设置当前话题"""
        self.context.current_topic = topic

    def update_pending_slots(self, slots: Dict[str, Any]):
        """更新待填槽位"""
        self.context.pending_slots.update(slots)

    def confirm_information(self, key: str, value: Any):
        """确认信息"""
        self.context.confirmed_info[key] = value
        # 从待填中移除
        if key in self.context.pending_slots:
            del self.context.pending_slots[key]

    def get_confirmed_info(self) -> Dict[str, Any]:
        """获取已确认信息"""
        return self.context.confirmed_info.copy()

    def get_conversation_summary(self, max_turns: int = 5) -> str:
        """获取对话摘要"""
        turns = self.get_history(max_turns)
        lines = []
        for turn in turns:
            prefix = "用户" if turn.role == "user" else "助手"
            lines.append(f"{prefix}: {turn.content}")
        return "\n".join(lines)

    def register_extractor(self, extractor: Callable[[str], Dict[str, Any]]):
        """注册信息提取器"""
        self._extractors.append(extractor)

    def _extract_information(self, content: str):
        """提取信息"""
        for extractor in self._extractors:
            try:
                info = extractor(content)
                if info:
                    self.context.confirmed_info.update(info)
            except Exception:
                pass

    def _trim_history(self):
        """修剪历史记录"""
        if len(self.context.turns) > self.max_history:
            # 保留最近的记录
            excess = len(self.context.turns) - self.max_history
            self.context.turns = self.context.turns[excess:]
            # 更新turn_id
            for i, turn in enumerate(self.context.turns):
                turn.turn_id = i

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "max_history": self.max_history,
            "context": self.context.to_dict() if self._context else None
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkingMemory":
        """从字典创建"""
        wm = cls(
            session_id=data.get("session_id"),
            max_history=data.get("max_history", 100)
        )
        if data.get("context"):
            wm._context = ConversationContext.from_dict(data["context"])
        return wm

    def clear(self):
        """清空工作记忆"""
        self._init_context()


# 便捷函数
def create_working_memory(session_id: Optional[str] = None) -> WorkingMemory:
    """创建工作记忆实例"""
    return WorkingMemory(session_id=session_id)