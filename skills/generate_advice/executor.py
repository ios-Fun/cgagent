"""generate_advice Skill executor - Hybrid advice generation."""

from typing import Dict, Any, List
from agent.llm_client import LLMClient


def execute(llm: LLMClient, sub_task: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute generate_advice skill.

    Args:
        llm: LLM client
        sub_task: Specific sub-task description
        context: Execution context with previous results

    Returns:
        Advice generation result
    """
    # Get previous step results
    parsed_data = _get_parsed_data(context)
    risk_data = _get_risk_data(context)

    if not parsed_data or not risk_data:
        return {
            "structured": {"error": "缺少前置步骤的输出"},
            "text": "无法生成建议：缺少体检报告解析或风险评估结果。"
        }

    # ─── Rule Engine: Generate advice items ───
    advice_items = []

    # Generate advice based on abnormal indicators
    for ind in parsed_data.get("indicators", []):
        if ind["status"] != "normal":
            advice_items.extend(_get_indicator_advice(ind))

    # Generate advice based on overall risk
    overall_risk = risk_data.get("overall_risk", {})
    if overall_risk.get("level") == "高风险":
        advice_items.append({
            "category": "就医建议",
            "priority": "紧急",
            "content": "建议尽快到医院进行详细检查"
        })

    # ─── Rule Engine: Generate follow-up plan ───
    followup_plan = _generate_followup_plan(parsed_data, risk_data)

    # ─── LLM: Natural language packaging ───
    formatted_advice = _generate_formatted_advice(
        llm, advice_items, followup_plan, overall_risk
    )

    return {
        "structured": {
            "advice_items": advice_items,
            "followup_plan": followup_plan
        },
        "text": formatted_advice,
        "metadata": {"execution_mode": "hybrid"}
    }


def _get_parsed_data(context: Dict) -> Dict:
    """Get parsed report data."""
    previous = context.get("previous_results", {})
    parse_result = previous.get("parse_report", {})
    if isinstance(parse_result, dict):
        return parse_result.get("structured", {})
    return {}


def _get_risk_data(context: Dict) -> Dict:
    """Get risk assessment data."""
    previous = context.get("previous_results", {})
    risk_result = previous.get("assess_risk", {})
    if isinstance(risk_result, dict):
        return risk_result.get("structured", {})
    return {}


def _get_indicator_advice(indicator: Dict) -> List[Dict]:
    """Generate advice based on abnormal indicator."""
    name = indicator["name"]
    status = indicator["status"]

    # Advice mapping
    advice_map = {
        "空腹血糖": [
            {"category": "饮食", "priority": "重要", "content": "控制碳水化合物摄入，避免高糖食物"}
        ],
        "血压": [
            {"category": "饮食", "priority": "重要", "content": "低盐饮食，每日食盐摄入<6g"},
            {"category": "运动", "priority": "建议", "content": "规律有氧运动，每周3-5次"}
        ],
        "收缩压": [
            {"category": "饮食", "priority": "重要", "content": "低盐饮食，每日食盐摄入<6g"},
            {"category": "运动", "priority": "建议", "content": "规律有氧运动，每周3-5次"}
        ],
        "舒张压": [
            {"category": "饮食", "priority": "重要", "content": "低盐饮食，每日食盐摄入<6g"},
            {"category": "运动", "priority": "建议", "content": "规律有氧运动，每周3-5次"}
        ],
        "尿酸": [
            {"category": "饮食", "priority": "重要", "content": "限制高嘌呤食物（海鲜、动物内脏、啤酒）"}
        ],
        "谷丙转氨酶": [
            {"category": "生活", "priority": "建议", "content": "避免饮酒，保证充足睡眠"}
        ],
        "谷草转氨酶": [
            {"category": "生活", "priority": "建议", "content": "避免饮酒，保证充足睡眠"}
        ],
        "BMI": [
            {"category": "运动", "priority": "重要", "content": "增加运动量，每周至少150分钟中等强度运动"}
        ],
        "甘油三酯": [
            {"category": "饮食", "priority": "重要", "content": "减少油脂和糖分摄入"},
            {"category": "运动", "priority": "建议", "content": "增加有氧运动"}
        ],
        "总胆固醇": [
            {"category": "饮食", "priority": "重要", "content": "减少高胆固醇食物（动物内脏、蛋黄等）"}
        ]
    }

    for key, advice in advice_map.items():
        if key in name:
            return advice

    return [{"category": "复查", "priority": "建议", "content": f"{name}异常，建议定期复查"}]


def _generate_followup_plan(parsed_data: Dict, risk_data: Dict) -> Dict:
    """Generate follow-up plan based on risk level."""
    overall_risk = risk_data.get("overall_risk", {})
    risk_level = overall_risk.get("level", "低风险")

    if risk_level == "高风险":
        return {
            "timing": "1-2周内",
            "items": ["全面复查", "专科就诊"],
            "note": "建议咨询相关科室医生"
        }
    elif risk_level == "中等风险":
        return {
            "timing": "1-3个月内",
            "items": ["重点指标复查"],
            "note": "改善生活方式后复查"
        }
    else:
        return {
            "timing": "年度体检",
            "items": ["常规体检"],
            "note": "保持健康生活方式"
        }


def _generate_formatted_advice(
    llm: LLMClient,
    advice_items: List[Dict],
    followup_plan: Dict,
    overall_risk: Dict
) -> str:
    """Generate formatted advice with LLM."""
    # Format advice items
    items_text = "\n".join([
        f"- [{item['category']}] {item['content']}"
        for item in advice_items
    ])

    prompt = f"""请将以下建议条目包装成连贯、专业的健康建议：

**建议条目：**
{items_text}

**风险等级：** {overall_risk.get('level', '未知')}

**复查计划：**
- 时间：{followup_plan['timing']}
- 项目：{', '.join(followup_plan['items'])}
- 备注：{followup_plan['note']}

请包含：
1. 总体建议（1-2句话）
2. 分类建议（按饮食、运动、生活等分类）
3. 复查计划建议
4. 温馨提示

语气要专业、鼓励、不过度焦虑。"""

    return llm.invoke(prompt)
