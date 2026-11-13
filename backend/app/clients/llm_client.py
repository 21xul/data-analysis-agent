"""LLM 客户端：自研护栏协议 + LangChain ChatOpenAI 工厂，两种入口并存。

- ``LLMClient`` / ``Decision``：现有 ReAct 链路的 function-calling 协议与错误分类（自研，保持不变）。
- ``build_chat_model()``：LangGraph 节点使用的 ``langchain_openai.ChatOpenAI``。

两者共用 app_config 里的模型配置与 .env 里的密钥；密钥只进内存，绝不打印。
"""
from __future__ import annotations

from typing import Any

from app.conf.app_config import app_config, effective_mode, secrets
from app.infra.llm_client import Decision, LLMClient  # noqa: F401 - 再导出

__all__ = ["LLMClient", "Decision", "build_chat_model", "chat_model_available"]


def build_chat_model() -> Any | None:
    """构造 ChatOpenAI；仅 real 模式 + 有密钥 + 依赖齐全时才启用。

    以 effective_mode()（环境变量优先、缺密钥自动降级）为准，避免 .env 里填了密钥
    就把默认 mock 规划器悄悄切成在线模型，导致离线回归与数字口径不稳定。
    """
    if effective_mode() != "real" or not secrets.has_llm_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except Exception:  # noqa: BLE001 - 可选依赖，缺失时静默降级
        return None
    return ChatOpenAI(
        model=app_config.llm.model,
        api_key=secrets.llm_api_key,
        base_url=app_config.llm.base_url,
        temperature=app_config.llm.temperature,
        timeout=app_config.llm.timeout_s,
        max_retries=app_config.llm.max_retries,
    )


def chat_model_available() -> bool:
    return build_chat_model() is not None
