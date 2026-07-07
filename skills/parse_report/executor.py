"""parse_report Skill executor - Hybrid rule engine + LLM."""

from typing import Dict, Any
from agent.llm_client import LLMClient
from shared.metrics_utils import (
    calculate_bmi, classify_bmi,
    classify_blood_pressure, check_indicator
)


def execute(llm: LLMClient, sub_task: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute parse_report skill.

    Args:
        llm: LLM client
        sub_task: Specific sub-task description
        context: Execution context

    Returns:
        Result with structured data and text
    """
    # Get raw report data from context
    raw = context.get("raw_report", {})
    if not raw:
        # Try to get from user input
        user_input = context.get("user_input", "")
        if "raw_report" in context:
            raw = context["raw_report"]
        else:
            # Return error if no data
            return {
                "structured": {"error": "No report data provided"},
                "text": "请提供体检报告数据。"
            }

    # ─── Rule Engine: Deterministic computation ───
    structured_result = {
        "basic_info": {},
        "indicators": [],
        "summary": {}
    }

    # Process basic information
    if "height" in raw and "weight" in raw:
        height = raw["height"]
        weight = raw["weight"]
        bmi = calculate_bmi(height, weight)
        bmi_category = classify_bmi(bmi)
        structured_result["basic_info"]["bmi"] = {
            "value": round(bmi, 1),
            "category": bmi_category
        }

    # Process blood pressure
    if "sbp" in raw and "dbp" in raw:
        sbp = raw.get("sbp", 0)
        dbp = raw.get("dbp", 0)
        bp_category = classify_blood_pressure(sbp, dbp)
        structured_result["basic_info"]["blood_pressure"] = {
            "sbp": sbp,
            "dbp": dbp,
            "category": bp_category
        }

    # Process lab indicators
    abnormal_count = 0
    for item in raw.get("lab_items", []):
        status, deviation = check_indicator(
            item.get("value"),
            item.get("ref_low"),
            item.get("ref_high")
        )

        indicator = {
            "name": item["name"],
            "value": item["value"],
            "unit": item.get("unit", ""),
            "status": status,
            "deviation_percent": deviation
        }

        if status != "normal":
            abnormal_count += 1
            indicator["ref_low"] = item.get("ref_low")
            indicator["ref_high"] = item.get("ref_high")

        structured_result["indicators"].append(indicator)

    structured_result["summary"]["total_indicators"] = len(structured_result["indicators"])
    structured_result["summary"]["abnormal_count"] = abnormal_count

    # ─── LLM: Natural language generation ───
    summary_prompt = _build_summary_prompt(structured_result)
    llm_summary = llm.invoke(summary_prompt)

    # ─── Merge and return ───
    return {
        "structured": structured_result,
        "text": llm_summary,
        "metadata": {
            "execution_mode": "hybrid",
            "abnormal_indicators": abnormal_count
        }
    }


def _build_summary_prompt(result: Dict) -> str:
    """Build LLM prompt for summary generation."""
    basic = result.get("basic_info", {})
    summary = result.get("summary", {})

    bmi_info = basic.get("bmi", {})
    bp_info = basic.get("blood_pressure", {})

    bmi_str = f"{bmi_info.get('value', 'N/A')} ({bmi_info.get('category', 'N/A')})"
    bp_str = f"{bp_info.get('sbp', 'N/A')}/{bp_info.get('dbp', 'N/A')} mmHg ({bp_info.get('category', 'N/A')})"

    abnormal_indicators = [
        ind["name"] for ind in result.get("indicators", [])
        if ind["status"] != "normal"
    ]

    prompt = f"""请用 2-3 句话概括以下体检结果：

**基本信息：**
- BMI: {bmi_str}
- 血压: {bp_str}

**检验指标：** 共 {summary.get('total_indicators', 0)} 项，异常 {summary.get('abnormal_count', 0)} 项

**异常指标：** {', '.join(abnormal_indicators) if abnormal_indicators else '无'}

请生成简洁、专业的体检概况概括。"""

    return prompt
