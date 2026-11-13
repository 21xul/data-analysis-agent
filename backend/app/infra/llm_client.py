"""OpenAI 兼容协议客户端（DashScope / 千问）。

明确不使用 LangChain 或任何 Agent 框架：function calling 的组装、解析、
错误归类与超时都在这里自行实现，编排层只依赖 decide() 这一个协议。
密钥只在内存中交给 SDK，不写日志、不进异常文本。
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

try:
    from openai import AsyncOpenAI
    _SDK_AVAILABLE = True
except ImportError:  # 可选依赖：mock 模式不需要安装 openai SDK
    AsyncOpenAI = None  # type: ignore[assignment]
    _SDK_AVAILABLE = False

from app.core.config import Settings
from app.core.errors import LLMUnavailable

_SENSITIVE = re.compile(r"sk-[A-Za-z0-9._\-]{8,}")


def _safe_error(exc: BaseException) -> str:
    """脱敏后的错误描述：只保留类型与精简信息，绝不回显凭据。"""
    text = f"{type(exc).__name__}: {exc}"[:240]
    return _SENSITIVE.sub("sk-***", text)


@dataclass
class Decision:
    """规划器的一步输出。tool_calls 为空即代表模型给出最终答案。"""
    thought: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    final: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def is_final(self) -> bool:
        return not self.tool_calls


class LLMClient:
    def __init__(self, settings: Settings):
        self.model = settings.model
        self.base_url = settings.base_url
        self._timeout = settings.step_timeout_s
        self._client = None
        self.unavailable_reason = ""
        if settings.api_key and _SDK_AVAILABLE and AsyncOpenAI is not None:
            # 不在任何地方记录 api_key 本身
            self._client = AsyncOpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
                timeout=settings.step_timeout_s,
                max_retries=1,
            )
        elif settings.api_key:
            self.unavailable_reason = "未安装 openai SDK，请执行 pip install -r requirements.txt"

    @property
    def available(self) -> bool:
        return self._client is not None

    async def decide(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Decision:
        if not self._client:
            raise LLMUnavailable("未配置模型凭据，无法使用真实规划器")
        try:
            resp = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.2,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LLMUnavailable("模型响应超时") from exc
        except Exception as exc:  # noqa: BLE001 - 统一转成脱敏的领域错误
            raise LLMUnavailable(_safe_error(exc)) from exc

        msg = resp.choices[0].message
        calls: list[dict[str, Any]] = []
        for tc in msg.tool_calls or []:
            calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "arguments": tc.function.arguments or "{}",
            })
        usage = {}
        if getattr(resp, "usage", None):
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        return Decision(
            thought=msg.content or "",
            tool_calls=calls,
            final=None if calls else (msg.content or ""),
            usage=usage,
        )

    async def check(self) -> dict[str, Any]:
        """连通性自检：只回状态与模型名，不回显密钥或原始响应体。"""
        if not self._client:
            return {"ok": False, "mode": "mock", "reason": "no_api_key"}
        try:
            await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                    temperature=0,
                ),
                timeout=min(self._timeout, 10),
            )
            return {"ok": True, "mode": "real", "model": self.model, "base_url": self.base_url}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "mode": "real", "model": self.model, "reason": _safe_error(exc)}
