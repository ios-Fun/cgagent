"""assess_risk Skill executor - Hybrid risk assessment."""

from typing import Dict, Any, List
from agent.llm_client import LLMClient


def execute(llm: LLMClient, sub_task: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute assess_risk skill.

    Args:
        llm: LLM client
        sub_task: Specific sub-task description
        context: Execution context with previous results

    Returns:
        Risk assessment result
    """
    # Get parsed report from previous step
    parsed_data = _get_parsed_data(context)
    if not parsed_data:
        return {
            "structured": {"error": "缺少 parse_report 的输出结果"},
            "text": "无法进行风险评估：缺少体检报告解析结果。"
        }

    # ─── Rule Engine: Risk scoring ───
    risk_scores = {
        "cardiovascular": _assess_cardiovascular_risk(parsed_data),
        "metabolic": _assess_metabolic_risk(parsed_data),
        "liver": _assess_liver_risk(parsed_data),
        "kidney": _assess_kidney_risk(parsed_data)
    }

    # Calculate overall risk
    overall_risk = _calculate_overall_risk(risk_scores)

    # ─── LLM: Risk reasoning explanation ───
    reasoning = _generate_reasoning(llm, risk_scores, overall_risk, parsed_data)

    return {
        "structured": {
            "risk_scores": risk_scores,
            "overall_risk": overall_risk
        },
        "text": reasoning,
        "metadata": {"execution_mode": "hybrid"}
    }


def _get_parsed_data(context: Dict) -> Dict:
    """Get parsed report data from context."""
    previous = context.get("previous_results", {})
    parse_result = previous.get("parse_report", {})

    if isinstance(parse_result, dict):
        return parse_result.get("structured", {})
    return {}


# ─── Risk assessment functions ───

def _assess_cardiovascular_risk(data: Dict) -> Dict:
    """Assess cardiovascular risk."""
    score = 0
    factors = []

    # Blood pressure assessment
    bp = data.get("basic_info", {}).get("blood_pressure", {})
    bp_category = bp.get("category", "")
    if "高血压" in bp_category:
        score += 30
        factors.append(f"血压异常({bp_category})")

    # BMI assessment
    bmi = data.get("basic_info", {}).get("bmi", {})
    bmi_category = bmi.get("category", "")
    if bmi_category in ["超重", "肥胖"]:
        score += 15
        factors.append(f"BMI {bmi.get('value', '')} ({bmi_category})")

    # Indicator assessment
    cardio_indicators = ["总胆固醇", "低密度脂蛋白", "甘油三酯", "高密度脂蛋白"]
    for ind in data.get("indicators", []):
        if ind["name"] in cardio_indicators and ind["status"] != "normal":
            score += 20
            factors.append(f"{ind['name']} {ind['status']}")

    level = _score_to_level(score)
    return {"score": min(score, 100), "level": level, "factors": factors}


def _assess_metabolic_risk(data: Dict) -> Dict:
    """Assess metabolic risk."""
    score = 0
    factors = []

    metabolic_indicators = ["空腹血糖", "糖化血红蛋白", "甘油三酯", "尿酸"]

    for ind in data.get("indicators", []):
        if ind["name"] in metabolic_indicators and ind["status"] != "normal":
            score += 25
            factors.append(f"{ind['name']} {ind['status']}")

    level = _score_to_level(score)
    return {"score": min(score, 100), "level": level, "factors": factors}


def _assess_liver_risk(data: Dict) -> Dict:
    """Assess liver risk."""
    score = 0
    factors = []

    liver_indicators = ["谷丙转氨酶", "谷草转氨酶", "谷氨酰转肽酶"]

    for ind in data.get("indicators", []):
        if ind["name"] in liver_indicators and ind["status"] != "normal":
            score += 35
            factors.append(f"{ind['name']} {ind['status']}")

    level = _score_to_level(score)
    return {"score": min(score, 100), "level": level, "factors": factors}


def _assess_kidney_risk(data: Dict) -> Dict:
    """Assess kidney risk."""
    score = 0
    factors = []

    kidney_indicators = ["肌酐", "尿素氮", "尿酸", "尿蛋白"]

    for ind in data.get("indicators", []):
        if ind["name"] in kidney_indicators and ind["status"] != "normal":
            score += 30
            factors.append(f"{ind['name']} {ind['status']}")

    level = _score_to_level(score)
    return {"score": min(score, 100), "level": level, "factors": factors}


def _calculate_overall_risk(risk_scores: Dict) -> Dict:
    """Calculate overall risk from dimensions."""
    avg_score = sum(s["score"] for s in risk_scores.values()) / len(risk_scores)

    if avg_score >= 70:
        level = "高风险"
        recommendation = "建议尽快就医，进行进一步检查"
    elif avg_score >= 40:
        level = "中等风险"
        recommendation = "建议改善生活方式，定期复查"
    else:
        level = "低风险"
        recommendation = "保持健康生活方式"

    return {
        "score": round(avg_score, 1),
        "level": level,
        "recommendation": recommendation
    }


def _score_to_level(score: int) -> str:
    """Convert score to level description."""
    if score >= 70:
        return "高风险"
    elif score >= 40:
        return "中等风险"
    else:
        return "低风险"


def _generate_reasoning(
    llm: LLMClient,
    risk_scores: Dict,
    overall_risk: Dict,
    parsed_data: Dict
) -> str:
    """Generate LLM risk reasoning explanation."""
    abnormal_indicators = _get_abnormal_indicators(parsed_data)

    prompt = f"""基于以下体检数据，请生成 3-5 句话的风险评估说明：

**各维度风险评分（0-100）：**
- 心血管风险: {risk_scores['cardiovascular']['score']} 分 ({risk_scores['cardiovascular']['level']})
- 代谢风险: {risk_scores['metabolic']['score']} 分 ({risk_scores['metabolic']['level']})
- 肝脏风险: {risk_scores['liver']['score']} 分 ({risk_scores['liver']['level']})
- 肾脏风险: {risk_scores['kidney']['score']} 分 ({risk_scores['kidney']['level']})

**总体风险: {overall_risk['level']}**

**异常指标: {', '.join(abnormal_indicators) if abnormal_indicators else '无'}**

请生成专业、客观的风险评估说明。"""

    return llm.invoke(prompt)


def _get_abnormal_indicators(data: Dict) -> List[str]:
    """Get list of abnormal indicators."""
    return [
        f"{ind['name']}={ind['value']}{ind.get('unit', '')}"
        for ind in data.get("indicators", [])
        if ind["status"] != "normal"
    ]
