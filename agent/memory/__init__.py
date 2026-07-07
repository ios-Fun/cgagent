"""
智能增强模块 - 对话记忆系统

提供短期工作记忆、用户画像和记忆管理能力
"""

from .working_memory import WorkingMemory, ConversationTurn, ConversationContext
from .user_profile import UserProfile, UserProfileManager
from .memory_manager import MemoryManager, MemoryEntry

__all__ = [
    "WorkingMemory",
    "ConversationTurn",
    "ConversationContext",
    "UserProfile",
    "UserProfileManager",
    "MemoryManager",
    "MemoryEntry",
]