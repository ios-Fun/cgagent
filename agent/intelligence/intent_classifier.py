"""
意图分类器模块

基于LLM的多意图识别，支持层次化意图和置信度评估。
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class IntentCategory(str, Enum):
    """意图主类别"""
    QUERY = "query"              # 信息查询
    ACTION = "action"            # 执行动作
    CREATIVE = "creative"        # 创造性任务
    CONVERSATIONAL = "chat"      # 闲聊/对话
    CLARIFICATION = "clarify"    # 寻求澄清
    OTHER = "other"              # 其他


@dataclass
class IntentConfidence:
    """意图置信度"""
    score: float                      # 0-1之间的置信度分数
    method: str                       # 评估方法 (llm/pattern/hybrid)
    low_confidence_reason: Optional[str] = None  # 置信度低的原因


@dataclass
class Intent:
    """意图数据类"""
    name: str
    confidence: float
    category: Optional[IntentCategory] = None
    description: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Intent:
    """Intent data class"""
    name: str
    confidence: float
    category: Optional[IntentCategory] = None
    description: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SubIntent:
    """Sub-intent"""
    name: str
    category: IntentCategory
    description: str
    confidence: IntentConfidence
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IntentClassificationResult:
    """意图分类结果"""
    primary_intent: str                           # 主意图名称
    primary_category: IntentCategory              # 主意图类别
    description: str                              # 意图描述
    confidence: IntentConfidence                  # 置信度
    sub_intents: List[SubIntent] = field(default_factory=list)  # 子意图列表
    slots: Dict[str, Any] = field(default_factory=dict)         # 提取的槽位
    needs_clarification: bool = False             # 是否需要澄清
    clarification_question: Optional[str] = None  # 澄清问题
    raw_response: Optional[str] = None            # LLM原始响应


@dataclass
class IntentExample:
    """意图示例"""
    utterance: str
    intent: str
    category: IntentCategory
    slots: Dict[str, Any] = field(default_factory=dict)


class IntentClassifier:
    """
    意图分类器

    基于LLM的多意图识别，支持层次化意图和置信度评估。
    当置信度低于阈值时，会主动请求澄清。
    """

    # 默认置信度阈值
    DEFAULT_CONFIDENCE_THRESHOLD = 0.7

    # 低置信度阈值（低于此值需要澄清）
    LOW_CONFIDENCE_THRESHOLD = 0.5

    # 意图类别描述
    CATEGORY_DESCRIPTIONS = {
        IntentCategory.QUERY: "用户想要获取信息、查询数据或寻求答案",
        IntentCategory.ACTION: "用户想要执行某个操作、完成任务或改变状态",
        IntentCategory.CREATIVE: "用户想要生成内容、创作或进行创造性任务",
        IntentCategory.CONVERSATIONAL: "用户进行闲聊、社交对话或建立关系",
        IntentCategory.CLARIFICATION: "用户需要澄清、解释或更多细节",
        IntentCategory.OTHER: "不属于以上类别的其他意图"
    }

    def __init__(
        self,
        llm_client: Any,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
        few_shot_examples: Optional[List[IntentExample]] = None,
        enable_hybrid: bool = True
    ):
        """
        初始化意图分类器

        Args:
            llm_client: LLM客户端，需要支持 acompletion 方法
            confidence_threshold: 置信度阈值，低于此值需要澄清
            low_confidence_threshold: 低置信度阈值，用于标记低置信度
            few_shot_examples: 少样本示例，用于提升分类准确率
            enable_hybrid: 是否启用混合模式（规则+LLM）
        """
        self.llm_client = llm_client
        self.confidence_threshold = confidence_threshold
        self.low_confidence_threshold = low_confidence_threshold
        self.few_shot_examples = few_shot_examples or []
        self.enable_hybrid = enable_hybrid

        # 规则匹配模式（用于混合模式）
        self._rule_patterns: Dict[str, List[re.Pattern]] = {}

    def add_rule_pattern(self, intent: str, patterns: List[str]):
        """
        添加规则匹配模式（用于混合模式）

        Args:
            intent: 意图名称
            patterns: 正则表达式模式列表
        """
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
        self._rule_patterns[intent] = compiled_patterns

    async def classify(
        self,
        user_input: str,
        conversation_context: Optional[Dict[str, Any]] = None
    ) -> IntentClassificationResult:
        """
        分类用户意图

        Args:
            user_input: 用户输入文本
            conversation_context: 对话上下文

        Returns:
            IntentClassificationResult: 意图分类结果
        """
        conversation_context = conversation_context or {}

        # 步骤1: 如果使用混合模式，先尝试规则匹配
        rule_based_result = None
        if self.enable_hybrid and self._rule_patterns:
            rule_based_result = self._try_rule_matching(user_input)

        # 步骤2: 使用LLM进行意图分类
        llm_result = await self._classify_with_llm(
            user_input,
            conversation_context,
            rule_hint=rule_based_result
        )

        # 步骤3: 合并规则匹配和LLM结果（如果启用了混合模式）
        final_result = self._merge_results(rule_based_result, llm_result)

        # 步骤4: 评估置信度并决定是否需要澄清
        final_result = self._evaluate_confidence(final_result)

        return final_result

    def _try_rule_matching(
        self,
        user_input: str
    ) -> Optional[Dict[str, Any]]:
        """
        尝试规则匹配

        Args:
            user_input: 用户输入

        Returns:
            匹配结果或None
        """
        for intent, patterns in self._rule_patterns.items():
            for pattern in patterns:
                match = pattern.search(user_input)
                if match:
                    return {
                        "intent": intent,
                        "matched_pattern": pattern.pattern,
                        "matched_text": match.group(),
                        "confidence": 0.85,  # 规则匹配的基础置信度
                        "method": "rule"
                    }
        return None

    async def _classify_with_llm(
        self,
        user_input: str,
        conversation_context: Dict[str, Any],
        rule_hint: Optional[Dict[str, Any]] = None
    ) -> IntentClassificationResult:
        """
        使用LLM进行意图分类

        Args:
            user_input: 用户输入
            conversation_context: 对话上下文
            rule_hint: 规则匹配的提示

        Returns:
            IntentClassificationResult: 分类结果
        """
        # 构建提示
        prompt = self._build_classification_prompt(
            user_input,
            conversation_context,
            rule_hint
        )

        # 调用LLM
        try:
            response = await self.llm_client.acompletion(
                messages=[
                    {"role": "system", "content": "你是一个专业的意图分类助手。请分析用户输入并返回结构化的意图分类结果。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # 低温度以获得更确定性的结果
                response_format={"type": "json_object"}
            )

            raw_content = response["choices"][0]["message"]["content"]
            parsed_result = json.loads(raw_content)

            return self._parse_llm_result(parsed_result, raw_content)

        except Exception as e:
            # LLM调用失败时的回退策略
            return self._create_fallback_result(user_input, str(e))

    def _build_classification_prompt(
        self,
        user_input: str,
        conversation_context: Dict[str, Any],
        rule_hint: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        构建分类提示

        Args:
            user_input: 用户输入
            conversation_context: 对话上下文
            rule_hint: 规则提示

        Returns:
            构建的提示字符串
        """
        prompt_parts = []

        # 1. 任务描述
        prompt_parts.append("请分析以下用户输入，识别其意图并提取相关信息。")
        prompt_parts.append("")

        # 2. 意图类别描述
        prompt_parts.append("## 意图类别")
        for category, description in self.CATEGORY_DESCRIPTIONS.items():
            prompt_parts.append(f"- {category.value}: {description}")
        prompt_parts.append("")

        # 3. 少样本示例（如果有）
        if self.few_shot_examples:
            prompt_parts.append("## 示例")
            for i, example in enumerate(self.few_shot_examples[:3], 1):  # 最多3个示例
                prompt_parts.append(f"示例{i}:")
                prompt_parts.append(f"  输入: {example.utterance}")
                prompt_parts.append(f"  意图: {example.intent} ({example.category.value})")
                if example.slots:
                    prompt_parts.append(f"  槽位: {example.slots}")
                prompt_parts.append("")

        # 4. 规则提示（如果有）
        if rule_hint:
            prompt_parts.append("## 规则匹配提示")
            prompt_parts.append(f"规则匹配结果: {rule_hint['intent']}")
            prompt_parts.append(f"匹配文本: {rule_hint['matched_text']}")
            prompt_parts.append("")

        # 5. 对话上下文（如果有）
        if conversation_context:
            recent_history = conversation_context.get("recent_history", [])
            if recent_history:
                prompt_parts.append("## 对话上下文（最近3轮）")
                for turn in recent_history[-3:]:
                    role = "用户" if turn.get("role") == "user" else "助手"
                    prompt_parts.append(f"{role}: {turn.get('content', '')}")
                prompt_parts.append("")

        # 6. 待分类的输入
        prompt_parts.append("## 待分类输入")
        prompt_parts.append(f"用户输入: {user_input}")
        prompt_parts.append("")

        # 7. 输出格式要求
        prompt_parts.append("## 输出格式")
        prompt_parts.append("请以JSON格式返回结果，包含以下字段:")
        prompt_parts.append(json.dumps({
            "primary_intent": "主意图名称（简短描述）",
            "primary_category": "主意图类别（从意图类别中选择）",
            "description": "意图的详细描述",
            "confidence": 0.85,
            "sub_intents": [
                {
                    "name": "子意图名称",
                    "category": "子意图类别",
                    "description": "子意图描述",
                    "confidence": 0.75,
                    "parameters": {}
                }
            ],
            "slots": {
                "槽位名": "槽位值"
            },
            "needs_clarification": False,
            "clarification_question": "如果需要澄清，提供澄清问题",
            "sentiment": "positive/neutral/negative",
            "urgency": "low/medium/high"
        }, indent=2, ensure_ascii=False))

        return "\n".join(prompt_parts)

    def _parse_llm_result(
        self,
        parsed: Dict[str, Any],
        raw_content: str
    ) -> IntentClassificationResult:
        """
        解析LLM返回的结果

        Args:
            parsed: 解析后的JSON
            raw_content: 原始响应内容

        Returns:
            IntentClassificationResult: 分类结果
        """
        # 提取主意图类别
        category_str = parsed.get("primary_category", "other").lower()
        try:
            primary_category = IntentCategory(category_str)
        except ValueError:
            primary_category = IntentCategory.OTHER

        # 提取置信度
        confidence_score = float(parsed.get("confidence", 0.5))
        confidence = IntentConfidence(
            score=confidence_score,
            method="llm",
            low_confidence_reason=None if confidence_score >= self.low_confidence_threshold else "confidence_below_threshold"
        )

        # 提取子意图
        sub_intents = []
        for sub in parsed.get("sub_intents", []):
            sub_category_str = sub.get("category", "other").lower()
            try:
                sub_category = IntentCategory(sub_category_str)
            except ValueError:
                sub_category = IntentCategory.OTHER

            sub_intents.append(SubIntent(
                name=sub.get("name", "unknown"),
                category=sub_category,
                description=sub.get("description", ""),
                confidence=IntentConfidence(
                    score=float(sub.get("confidence", 0.5)),
                    method="llm"
                ),
                parameters=sub.get("parameters", {})
            ))

        # 构建最终结果
        result = IntentClassificationResult(
            primary_intent=parsed.get("primary_intent", "unknown"),
            primary_category=primary_category,
            description=parsed.get("description", ""),
            confidence=confidence,
            sub_intents=sub_intents,
            slots=parsed.get("slots", {}),
            needs_clarification=parsed.get("needs_clarification", False),
            clarification_question=parsed.get("clarification_question"),
            raw_response=raw_content
        )

        # 根据置信度自动设置是否需要澄清
        if result.confidence.score < self.confidence_threshold:
            result.needs_clarification = True
            if not result.clarification_question:
                result.clarification_question = self._generate_clarification_question(result)

        return result

    def _create_fallback_result(
        self,
        user_input: str,
        error_message: str
    ) -> IntentClassificationResult:
        """
        创建回退结果（当LLM调用失败时）

        Args:
            user_input: 用户输入
            error_message: 错误信息

        Returns:
            IntentClassificationResult: 回退结果
        """
        return IntentClassificationResult(
            primary_intent="unknown",
            primary_category=IntentCategory.OTHER,
            description=f"分类失败: {error_message}",
            confidence=IntentConfidence(
                score=0.0,
                method="fallback",
                low_confidence_reason=f"llm_error: {error_message}"
            ),
            sub_intents=[],
            slots={},
            needs_clarification=True,
            clarification_question="抱歉，我没能理解您的意思。您能重新描述一下您的需求吗？"
        )

    def _generate_clarification_question(
        self,
        result: IntentClassificationResult
    ) -> str:
        """
        生成澄清问题

        Args:
            result: 分类结果

        Returns:
            澄清问题
        """
        # 根据主意图类别生成不同的澄清问题
        clarification_questions = {
            IntentCategory.QUERY: "您是想查询什么信息呢？",
            IntentCategory.ACTION: "您希望我帮您执行什么操作？",
            IntentCategory.CREATIVE: "您希望我创建什么内容？",
            IntentCategory.CONVERSATIONAL: "您想聊些什么话题？",
            IntentCategory.CLARIFICATION: "您需要我澄清什么？",
            IntentCategory.OTHER: "抱歉，我没能完全理解。您能详细说明一下吗？"
        }

        return clarification_questions.get(
            result.primary_category,
            "抱歉，我没能完全理解您的意思。您能重新描述一下吗？"
        )

    def _evaluate_confidence(
        self,
        result: IntentClassificationResult
    ) -> IntentClassificationResult:
        """
        评估置信度并决定是否需要澄清

        Args:
            result: 分类结果

        Returns:
            评估后的结果
        """
        score = result.confidence.score

        # 如果置信度低于阈值，标记需要澄清
        if score < self.confidence_threshold:
            result.needs_clarification = True
            result.confidence.low_confidence_reason = f"confidence_score {score:.2f} below threshold {self.confidence_threshold}"

            if not result.clarification_question:
                result.clarification_question = self._generate_clarification_question(result)

        return result

    def _merge_results(
        self,
        rule_result: Optional[Dict[str, Any]],
        llm_result: IntentClassificationResult
    ) -> IntentClassificationResult:
        """
        合并规则匹配和LLM分类结果

        Args:
            rule_result: 规则匹配结果
            llm_result: LLM分类结果

        Returns:
            合并后的结果
        """
        if not rule_result:
            return llm_result

        # 如果规则匹配和LLM结果一致，提高置信度
        if rule_result["intent"].lower() in llm_result.primary_intent.lower():
            llm_result.confidence.score = min(1.0, llm_result.confidence.score + 0.1)
            llm_result.confidence.method = "hybrid"

        return llm_result