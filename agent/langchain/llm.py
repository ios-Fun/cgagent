from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agent.yaml_settings import get_section


def _synthesis_settings() -> dict:
    synth = get_section("synthesis_llm")
    llm = get_section("llm")
    provider = (
        synth.get("provider")
        or llm.get("provider")
        or "ollama"
    )
    return {
        "provider": str(provider).lower(),
        "model": synth.get("model") or llm.get("model") or "Jarcgon/Qwen3.6-35B-A3B-Claude-4.7-Opus-abliterated-uncenfull",
        "api_key": synth.get("api_key") if synth.get("api_key") not in (None, "") else llm.get("api_key"),
        "base_url": synth.get("base_url") or llm.get("base_url") or "http://192.168.0.54:11434",
        "temperature": float(synth.get("temperature", llm.get("temperature", 0.4))),
        "max_tokens": int(synth.get("max_tokens", llm.get("max_tokens", 8192))),
        "system_template": (
            synth.get("system_template")
            or "你是一位电力行业的**预警分析专家**。你需要综合利用设备诊断、故障推导、实时测点和历史知识，对设备健康状态进行评估，并给出分级处理建议。"
        ),
    }


def _build_chat_model(cfg: dict) -> Any:
    provider = cfg["provider"]
    common = {
        "model": cfg["model"],
        "temperature": cfg["temperature"],
    }
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            **common,
            base_url=cfg["base_url"],
            max_tokens=cfg["max_tokens"],
        )

    # openai / deepseek / zhipu 等 OpenAI 兼容接口
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        **common,
        "api_key": cfg.get("api_key") or "EMPTY",
        "max_tokens": cfg["max_tokens"],
    }
    if cfg.get("base_url"):
        kwargs["base_url"] = cfg["base_url"]
    return ChatOpenAI(**kwargs)


def generate_context(
    context: str,
    memory_context: Optional[str] = None,
    *,
    user_input: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> str:
    cfg = _synthesis_settings()
    llm = _build_chat_model(cfg)

    system_content = (system_prompt or str(cfg["system_template"])).strip()
    if memory_context and memory_context.strip():
        system_content = f"{system_content}\n\n{memory_context.strip()}"

    if user_input and user_input.strip():
        human = (
            f"# 用户问题\n{user_input.strip()}\n\n"
            f"# 参考内容（skill 执行结果 / 工具数据，请据此回答；勿编造）\n"
            f"{(context or '').strip() or '(无参考内容)'}\n\n"
            "请综合以上参考内容，直接用专业中文回答用户问题。"
        )
    else:
        human = context or ""

    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content=human),
    ]
    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        print(f"调用 LLM 失败：{e}")
        return "调用 LLM 失败"
