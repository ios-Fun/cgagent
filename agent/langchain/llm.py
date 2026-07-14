from typing import Optional

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

from agent.yaml_settings import get_section


def _synthesis_settings() -> dict:
    synth = get_section("synthesis_llm")
    llm = get_section("llm")
    return {
        "model": synth.get("model") or llm.get("model") or "Jarcgon/Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-uncenfull",
        "base_url": synth.get("base_url") or llm.get("base_url") or "http://192.168.0.54:11434",
        "temperature": float(synth.get("temperature", llm.get("temperature", 0.4))),
        "max_tokens": int(synth.get("max_tokens", llm.get("max_tokens", 8192))),
        "system_template": (
            synth.get("system_template")
            or "你是一位电力行业的**预警分析专家**。你需要综合利用设备诊断、故障推导、实时测点和历史知识，对设备健康状态进行评估，并给出分级处理建议。"
        ),
    }


def generate_context(context: str, memory_context: Optional[str] = None) -> str:
    cfg = _synthesis_settings()
    llm = ChatOllama(
        model=cfg["model"],
        base_url=cfg["base_url"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
    )

    system_content = str(cfg["system_template"]).strip()
    if memory_context and memory_context.strip():
        system_content = f"{system_content}\n\n{memory_context.strip()}"

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=context),
    ]
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        print(f"调用 LLM 失败：{e}")
        return "调用 LLM 失败"
