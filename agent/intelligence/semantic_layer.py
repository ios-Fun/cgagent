"""
语义理解层统一接口

整合意图分类和槽位填充，提供统一的语义理解能力
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable

from .intent_classifier import (
    IntentClassifier, IntentClassificationResult, Intent, IntentConfidence
)
from .slot_filler import (
    SlotFiller, SlotFillingResult, SlotDefinition, SlotType, SlotValue
)


@dataclass
class SemanticUnderstandingResult:
    """语义理解完整结果"""
    # 原始输入
    user_input: str

    # 意图理解
    intent: Optional[Intent] = None
    secondary_intents: List[Intent] = field(default_factory=list)
    intent_confidence: float = 0.0
    intent_confidence_level: str = "low"

    # 槽位填充
    slots: Dict[str, Any] = field(default_factory=dict)
    slot_confidences: Dict[str, float] = field(default_factory=dict)
    missing_slots: List[str] = field(default_factory=list)
    invalid_slots: List[str] = field(default_factory=list)

    # 交互状态
    clarification_needed: bool = False
    clarification_question: str = ""
    ambiguity_detected: bool = False
    follow_up_questions: List[str] = field(default_factory=list)

    # 上下文
    conversation_context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_clear(self) -> bool:
        """语义理解是否清晰（无需澄清）"""
        return (not self.clarification_needed and
                self.intent_confidence_level in ("high", "medium") and
                len(self.missing_slots) == 0 and
                len(self.invalid_slots) == 0)

    def is_ready_for_execution(self) -> bool:
        """是否准备好执行"""
        return (self.intent is not None and
                self.intent_confidence > 0.3 and
                len(self.missing_slots) == 0)

    def get_execution_plan_input(self) -> Dict[str, Any]:
        """获取执行计划输入"""
        return {
            "intent": self.intent.name if self.intent else None,
            "intent_confidence": self.intent_confidence,
            "parameters": self.slots,
            "requires_clarification": self.clarification_needed,
            "metadata": self.metadata
        }


class SemanticLayer:
    """
    语义理解层统一接口

    整合意图分类器和槽位填充器，提供端到端的语义理解能力
    """

    def __init__(self, llm_client=None, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.llm_client = llm_client

        # 初始化组件
        self.intent_classifier = IntentClassifier(llm_client, config.get("intent"))
        self.slot_filler = SlotFiller(llm_client, config.get("slot"))

        # 配置
        self.min_confidence = self.config.get("min_confidence", 0.5)
        self.use_intent_for_slots = self.config.get("use_intent_for_slots", True)

        # 回调函数
        self.on_intent_classified: Optional[Callable[[IntentClassificationResult], None]] = None
        self.on_slots_filled: Optional[Callable[[SlotFillingResult], None]] = None

    def understand(self, user_input: str,
                   conversation_context: Optional[Dict[str, Any]] = None,
                   available_skills: Optional[List[str]] = None) -> SemanticUnderstandingResult:
        """
        执行完整的语义理解

        Args:
            user_input: 用户输入
            conversation_context: 对话上下文
            available_skills: 可用技能列表

        Returns:
            SemanticUnderstandingResult: 语义理解结果
        """
        result = SemanticUnderstandingResult(user_input=user_input)

        # 1. 意图分类
        intent_result = self.intent_classifier.classify(
            user_input,
            conversation_context.get("history", []) if conversation_context else None,
            available_skills
        )

        if self.on_intent_classified:
            self.on_intent_classified(intent_result)

        # 填充意图信息
        result.intent = intent_result.get_top_intent()
        result.secondary_intents = intent_result.secondary_intents
        result.intent_confidence = intent_result.get_confidence()
        result.intent_confidence_level = (
            result.intent.get_confidence_level().value if result.intent else "low"
        )
        result.clarification_needed = intent_result.clarification_needed
        result.clarification_question = intent_result.clarification_question
        result.ambiguity_detected = intent_result.ambiguity_detected

        # 2. 槽位填充
        if result.intent or not self.use_intent_for_slots:
            # 根据意图获取相关槽位定义
            slot_result = self.slot_filler.fill_slots(
                user_input,
                intent_name=result.intent.name if result.intent else None,
                context=conversation_context
            )

            if self.on_slots_filled:
                self.on_slots_filled(slot_result)

            # 填充槽位信息
            result.slots = slot_result.get_all_values()
            result.missing_slots = slot_result.missing_required
            result.invalid_slots = slot_result.invalid_slots
            result.follow_up_questions = slot_result.follow_up_questions
            result.slot_confidences = {
                name: slot.confidence for name, slot in slot_result.slots.items()
            }

        # 3. 综合评估
        if not result.clarification_needed:
            if result.intent_confidence < self.min_confidence:
                result.clarification_needed = True
                result.clarification_question = "我不太确定您的意图，能否请您更具体地描述一下？"

        return result

    def quick_understand(self, user_input: str) -> Dict[str, Any]:
        """快速理解（简化接口）"""
        result = self.understand(user_input)
        return {
            "intent": result.intent.name if result.intent else None,
            "confidence": result.intent_confidence,
            "slots": result.slots,
            "needs_clarification": result.clarification_needed
        }

    def register_intent_slots(self, intent_name: str, slot_definitions: List[SlotDefinition]):
        """为特定意图注册槽位定义"""
        # 这里可以实现意图-槽位映射关系
        for slot_def in slot_definitions:
            self.slot_filler.register_slot(slot_def)


# 便捷的工厂函数
def create_semantic_layer(llm_client=None, config: Optional[Dict[str, Any]] = None) -> SemanticLayer:
    """创建语义理解层实例"""
    return SemanticLayer(llm_client, config)