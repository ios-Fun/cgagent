"""
智能增强模块 - 对话记忆系统

对齐 deerflow memory：
- 用户画像（user/history/facts）
- LLM 更新 + 规则兜底
- 防抖异步队列
- 系统提示词注入
存储：SQLite（user_memory_profiles + long_term_memories）
"""

from .working_memory import WorkingMemory, ConversationTurn, ConversationContext
from .user_profile import UserProfile, UserProfileManager
from .memory_manager import MemoryManager, MemoryEntry
from .config import MemoryConfig, get_memory_config, set_memory_config
from .prompt import (
    MEMORY_UPDATE_PROMPT,
    FACT_EXTRACTION_PROMPT,
    format_memory_for_injection,
    format_conversation_for_update,
)
from .queue import ConversationContext as MemoryConversationContext, MemoryUpdateQueue, get_memory_queue, reset_memory_queue
from .storage import (
    MemoryStorage,
    SqliteMemoryStorage,
    get_memory_storage,
    create_empty_memory,
)
from .updater import (
    MemoryUpdater,
    clear_memory_data,
    delete_memory_fact,
    get_memory_data,
    reload_memory_data,
    update_memory_from_conversation,
    create_memory_fact,
)
from .message_processing import (
    filter_messages_for_memory,
    detect_correction,
    detect_reinforcement,
)
from .long_term_memory import (
    LongTermMemoryService,
    LongTermMemoryStore,
    LongTermMemoryModel,
    LongTermMemoryType,
    MemoryItem,
    get_long_term_memory_service,
    format_memories_for_prompt,
    extract_memories_from_text,
)

__all__ = [
    "WorkingMemory",
    "ConversationTurn",
    "ConversationContext",
    "UserProfile",
    "UserProfileManager",
    "MemoryManager",
    "MemoryEntry",
    "MemoryConfig",
    "get_memory_config",
    "set_memory_config",
    "MEMORY_UPDATE_PROMPT",
    "FACT_EXTRACTION_PROMPT",
    "format_memory_for_injection",
    "format_conversation_for_update",
    "MemoryConversationContext",
    "MemoryUpdateQueue",
    "get_memory_queue",
    "reset_memory_queue",
    "MemoryStorage",
    "SqliteMemoryStorage",
    "get_memory_storage",
    "create_empty_memory",
    "MemoryUpdater",
    "clear_memory_data",
    "delete_memory_fact",
    "get_memory_data",
    "reload_memory_data",
    "update_memory_from_conversation",
    "create_memory_fact",
    "filter_messages_for_memory",
    "detect_correction",
    "detect_reinforcement",
    "LongTermMemoryService",
    "LongTermMemoryStore",
    "LongTermMemoryModel",
    "LongTermMemoryType",
    "MemoryItem",
    "get_long_term_memory_service",
    "format_memories_for_prompt",
    "extract_memories_from_text",
]
