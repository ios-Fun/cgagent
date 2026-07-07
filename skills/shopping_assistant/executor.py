"""智能导购助手执行器 - LLM驱动的真正智能助手"""

import json
import logging
import re
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

from .schema import (
    DialogueState, UserIntent, Product, UserPreference,
    Conversation, Message, AssistantResponse, ToolCall
)
from .tools import TOOLS_REGISTRY, format_tools_for_llm
from .utils import ProductKnowledgeBase

logger = logging.getLogger(__name__)


class ShoppingAssistant:
    """
    智能导购助手

    基于LLM的真正智能购物助手，能够：
    - 自然理解用户需求
    - 智能推荐商品
    - 多轮对话管理
    - 商品对比和咨询
    """

    def __init__(self, llm_client=None):
        """
        初始化助手

        Args:
            llm_client: LLM客户端，需要支持 invoke() 方法
        """
        self.llm_client = llm_client
        self.knowledge_base = ProductKnowledgeBase()
        self.conversations: Dict[str, Conversation] = {}

        # 系统提示词
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        tools_desc = format_tools_for_llm()

        return f"""你是一位专业、友好的智能导购助手，名字叫"小购"。你的目标是帮助用户找到最合适的商品。

## 你的能力
1. **需求理解**: 通过对话理解用户的购物需求，包括商品类别、预算、品牌偏好、使用场景等
2. **智能推荐**: 根据用户需求推荐最合适的商品，并说明推荐理由
3. **商品对比**: 对比多款商品的优缺点，帮助用户做出选择
4. **商品咨询**: 解答关于商品规格、功能、价格等问题

## 可用工具
{tools_desc}

## 工作流程
1. **需求收集**: 如果用户需求不明确，主动询问缺失信息（类别、预算、用途等）
2. **商品检索**: 使用 search_products 工具搜索匹配的商品
3. **推荐展示**: 向用户展示推荐结果，包括商品名称、价格、核心配置和推荐理由
4. **跟进服务**: 询问用户是否需要了解更多详情、对比商品或查看其他选择

## 对话风格
- 友好、专业、耐心
- 使用简洁明了的语言
- 主动提供建议但不过度推销
- 记住用户的偏好，避免重复询问

## 响应格式
你的响应应该是自然的对话文本。当你需要调用工具时，按以下格式输出：

```json
{{
    "thought": "你的思考过程",
    "tool_calls": [
        {{"name": "工具名", "arguments": {{"参数": "值"}}}}
    ],
    "response": "给用户的回复（如果有必要的话）"
}}
```

如果不需要调用工具，直接返回：
```json
{{
    "thought": "你的思考过程",
    "response": "给用户的回复"
}}
```

## 重要提醒
- 每次搜索时最多返回3-5个最佳匹配结果
- 推荐时要说明推荐理由，结合用户的具体需求
- 如果用户预算紧张，优先推荐性价比高的产品
- 如果用户追求品质，推荐旗舰产品
- 保持对话连贯，记住之前讨论过的内容
"""

    async def chat(
        self,
        message: str,
        user_id: str,
        session_id: Optional[str] = None
    ) -> AssistantResponse:
        """
        与用户对话

        Args:
            message: 用户消息
            user_id: 用户ID
            session_id: 会话ID，如果为空则创建新会话

        Returns:
            助手响应
        """
        # 获取或创建会话
        if session_id is None:
            session_id = f"{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        if session_id not in self.conversations:
            self.conversations[session_id] = Conversation(
                session_id=session_id,
                user_id=user_id,
                state=DialogueState.GREETING
            )

        conversation = self.conversations[session_id]

        # 添加用户消息
        conversation.add_message("user", message)

        # 构建对话上下文
        context = self._build_context(conversation)

        # 调用LLM
        llm_response = await self._call_llm(message, context)

        # 处理LLM响应
        response = await self._process_llm_response(llm_response, conversation)

        # 添加助手回复到历史
        conversation.add_message("assistant", response.content, {
            "tool_calls": [tc.name for tc in response.tool_calls],
            "products": [p.id for p in response.products]
        })

        return response

    def _build_context(self, conversation: Conversation) -> str:
        """构建对话上下文"""
        lines = []

        # 当前偏好
        if conversation.user_preference.category:
            lines.append(f"用户偏好类别: {conversation.user_preference.category}")
        if conversation.user_preference.brands:
            lines.append(f"用户偏好品牌: {', '.join(conversation.user_preference.brands)}")
        if conversation.user_preference.price_range:
            pr = conversation.user_preference.price_range
            lines.append(f"用户预算范围: ¥{pr.get('min', 0)} - ¥{pr.get('max', '不限')}")

        # 最近讨论的商品
        if conversation.current_products:
            lines.append(f"最近讨论的商品: {', '.join([p.name for p in conversation.current_products[-3:]])}")

        # 对话状态
        lines.append(f"当前对话状态: {conversation.state.value}")

        return "\n".join(lines) if lines else "新对话，无历史信息"

    async def _call_llm(self, user_message: str, context: str) -> str:
        """调用LLM"""
        if self.llm_client is None:
            # 模拟LLM响应（用于测试）
            return self._mock_llm_response(user_message, context)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"## 当前上下文\n{context}\n\n## 用户消息\n{user_message}"}
        ]

        try:
            response = await self.llm_client.invoke(messages)
            return response
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return f"抱歉，我遇到了一些问题：{str(e)}"

    def _mock_llm_response(self, user_message: str, context: str) -> str:
        """模拟LLM响应（用于没有LLM客户端的情况）"""
        # 简单的规则匹配，实际应该使用真正的LLM
        msg_lower = user_message.lower()

        # 检测意图和实体
        category = None
        for cat in ["笔记本", "手机", "耳机"]:
            if cat in user_message:
                category = cat
                break

        price_range = None
        price_match = re.search(r'(\d{3,5})', user_message)
        if price_match:
            price = int(price_match.group(1))
            price_range = {"min": 0, "max": price * 1.2}

        # 如果有类别信息，认为是推荐请求
        if category or price_match:
            return self._mock_recommendation_response(user_message, context, category, price_range)

        elif any(kw in msg_lower for kw in ["对比", "哪个好", "区别"]):
            # 需要对比
            return self._mock_comparison_response(user_message, context)

        elif any(kw in msg_lower for kw in ["多少钱", "价格"]):
            # 价格咨询
            return '{"response": "您想了解哪款商品的价格呢？我可以帮您查询。"}'

        else:
            # 默认响应 - 询问需求
            return '{"response": "您好！我是智能导购助手小购。请问您想买什么商品呢？比如笔记本、手机、耳机等，告诉我您的预算和用途，我来为您推荐最合适的产品。"}'

    def _mock_recommendation_response(self, user_message: str, context: str, category: str = None, price_range: dict = None) -> str:
        """模拟推荐响应"""
        # 构建工具调用
        tool_args = {"limit": 5}
        if category:
            tool_args["category"] = category
        if price_range:
            tool_args["max_price"] = price_range["max"]

        return json.dumps({
            "thought": f"用户想要推荐，类别={category}，预算={price_range}",
            "tool_calls": [
                {"name": "search_products", "arguments": tool_args}
            ],
            "response": None
        })

    def _mock_comparison_response(self, user_message: str, context: str) -> str:
        """模拟对比响应"""
        return json.dumps({
            "thought": "用户想要对比商品",
            "response": "请告诉我您想对比哪几款商品？我可以帮您详细分析它们的优缺点。"
        })

    async def _process_llm_response(
        self,
        llm_response: str,
        conversation: Conversation
    ) -> AssistantResponse:
        """处理LLM响应"""
        try:
            # 尝试解析JSON
            data = json.loads(llm_response)

            tool_calls = []
            products = []

            # 执行工具调用
            if "tool_calls" in data and data["tool_calls"]:
                for tc in data["tool_calls"]:
                    tool_name = tc["name"]
                    tool_args = tc.get("arguments", {})

                    if tool_name in TOOLS_REGISTRY:
                        tool_func = TOOLS_REGISTRY[tool_name]["function"]
                        result = tool_func(**tool_args)

                        tool_calls.append(ToolCall(
                            name=tool_name,
                            arguments=tool_args,
                            result=result
                        ))

                        # 收集商品
                        if "products" in result:
                            from .utils import ProductKnowledgeBase
                            kb = ProductKnowledgeBase()
                            for p_data in result["products"]:
                                p = kb.get_product(p_data["id"])
                                if p:
                                    products.append(p)
                                    conversation.current_products.append(p)

            # 生成或获取响应文本
            response_text = data.get("response")

            # 如果有工具结果但没有响应文本，生成响应
            if tool_calls and not response_text:
                response_text = self._generate_response_from_tool_results(
                    tool_calls, products, conversation
                )

            # 更新对话状态
            if tool_calls:
                conversation.state = DialogueState.RECOMMENDING

            # 如果还是没有响应，使用默认
            if not response_text:
                response_text = "您好！我是小购，请问有什么可以帮您的？"

            return AssistantResponse(
                content=response_text,
                tool_calls=tool_calls,
                state=conversation.state,
                products=products
            )

        except json.JSONDecodeError:
            # 不是JSON，直接作为响应文本
            return AssistantResponse(
                content=llm_response,
                state=conversation.state
            )
        except Exception as e:
            logger.error(f"处理LLM响应失败: {e}")
            return AssistantResponse(
                content="抱歉，我遇到了一些问题。请稍后再试。",
                state=conversation.state
            )

    def _generate_response_from_tool_results(
        self,
        tool_calls: List[ToolCall],
        products: List[Product],
        conversation: Conversation
    ) -> str:
        """根据工具结果生成响应"""
        if not products:
            return "抱歉，没有找到符合您需求的商品。您可以调整一下筛选条件，比如预算范围或品牌偏好。"

        # 生成推荐响应
        lines = ["根据您的需求，我为您找到以下几款不错的商品：\n"]

        for i, p in enumerate(products[:3], 1):
            lines.append(f"### {i}. {p.name}")
            lines.append(f"- 💰 价格：¥{p.price}")
            lines.append(f"- ⭐ 评分：{p.rating}分 | 销量：{p.sales}")

            # 生成推荐理由
            reasons = self._generate_recommendation_reasons(p, conversation)
            lines.append(f"- ✨ 推荐理由：{reasons}")

            # 核心配置
            attrs = []
            for key in ["processor", "screen", "battery", "camera", "noise_cancelling"]:
                if key in p.attributes:
                    attrs.append(f"{key}: {p.attributes[key]}")
            if attrs:
                lines.append(f"- 🔧 配置：{', '.join(attrs[:3])}")
            lines.append("")

        lines.append("请问您对哪款比较感兴趣？我可以为您详细介绍，或者帮您对比一下这几款的区别。")

        return "\n".join(lines)

    def _generate_recommendation_reasons(
        self,
        product: Product,
        conversation: Conversation
    ) -> str:
        """生成推荐理由"""
        reasons = []

        # 基于评分
        if product.rating >= 4.8:
            reasons.append("用户评价极高")
        elif product.rating >= 4.5:
            reasons.append("口碑很好")

        # 基于销量
        if product.sales >= 100000:
            reasons.append("热销爆款")

        # 基于标签
        if conversation.user_preference.use_case:
            if conversation.user_preference.use_case == "游戏" and "游戏" in product.tags:
                reasons.append("专为游戏优化")
            elif conversation.user_preference.use_case == "办公" and "办公" in product.tags:
                reasons.append("办公首选")

        # 性价比
        if conversation.user_preference.price_range:
            max_price = conversation.user_preference.price_range.get("max", 0)
            if max_price > 0 and product.price <= max_price * 0.8:
                reasons.append("性价比突出")

        return "、".join(reasons) if reasons else "综合表现优秀"

    def get_conversation(self, session_id: str) -> Optional[Conversation]:
        """获取会话"""
        return self.conversations.get(session_id)

    def clear_conversation(self, session_id: str):
        """清除会话"""
        if session_id in self.conversations:
            del self.conversations[session_id]


# 对外接口
async def execute(
    llm_client,
    user_input: str,
    user_id: str = "default_user",
    session_id: str = None,
    context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    执行智能导购

    Args:
        llm_client: LLM客户端
        user_input: 用户输入
        user_id: 用户ID
        session_id: 会话ID
        context: 额外上下文

    Returns:
        执行结果
    """
    assistant = ShoppingAssistant(llm_client)

    result = await assistant.chat(
        message=user_input,
        user_id=user_id,
        session_id=session_id
    )

    return {
        "structured": {
            "state": result.state.value,
            "products": [p.to_dict() for p in result.products],
            "tool_calls": [tc.name for tc in result.tool_calls]
        },
        "text": result.content
    }
