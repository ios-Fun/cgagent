REFLECTION_PROMPT = """你是一个电厂报告审核员。请审查以下研究报告，判断是否需要需要调整。

当前报告：
{report}

只返回JSON，不返回其他内容：
{{
    "is_sufficient": true或false,
    "additional_adjusts": ["结束日期时间不是当天", "不要出现系统内部ID"]
}}

注意：
- 如果报告已基本没有问题，返回 is_sufficient: true，additional_queries为空列表
- 只有明显缺失核心内容时才返回 false
- additional_adjusts 最多5个
"""


