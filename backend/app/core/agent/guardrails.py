"""护栏：工具白名单、参数校验、步数、单步工具数、重复调用与总超时。"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.errors import GuardrailError


@dataclass
class Guardrails:
    allowed: set[str]
    max_steps: int = 8
    max_calls_per_step: int = 3
    total_timeout_s: float = 90.0

    def check(
        self,
        *,
        name: str,
        arguments: str | dict,
        signatures: set[str],
        step: int,
        elapsed: float,
    ) -> str:
        if step >= self.max_steps:
            raise GuardrailError("已达到最大推理步数")
        if elapsed > self.total_timeout_s:
            raise GuardrailError("分析总时长超限")
        if name not in self.allowed:
            raise GuardrailError(f"工具 {name} 不在白名单内")
        raw = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        sig = f"{name}:{raw}"
        if sig in signatures:
            raise GuardrailError(f"检测到重复调用：{name}")
        signatures.add(sig)
        return raw
