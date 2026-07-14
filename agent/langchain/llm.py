from langchain_ollama import ChatOllama

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

SYSTEM_TEMPLATE = """你是一位电力行业的**预警分析专家**。你需要综合利用设备诊断、故障推导、实时测点和历史知识，对设备健康状态进行评估，并给出分级处理建议。"""

def generate_context(context:str)-> str:
    llm = ChatOllama(
        model="Jarcgon/Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-uncenfull",  # 必须和 `ollama run` 的模型名完全匹配
        base_url= "http://192.168.0.54:11434",
        temperature=0.4,
        max_tokens=8192
    )

    messages = [
        SystemMessage(content=SYSTEM_TEMPLATE),

        HumanMessage(content=context)
    ]
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        print(f"调用 LLM 失败：{e}")
        return "调用 LLM 失败"