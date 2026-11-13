"""工具注册表：把领域函数暴露为 OpenAI function calling 的 JSON Schema。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from app.core.errors import ToolError, UnknownTool


@dataclass
class ToolContext:
    frame: pd.DataFrame
    dataset_name: str
    columns: list[dict[str, Any]]
    conn: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    def number_columns(self) -> list[str]:
        return [c["label"] for c in self.columns if c.get("type") == "number"]

    def date_column(self) -> str | None:
        for c in self.columns:
            if c.get("type") == "date":
                return c["label"]
        return None

    def category_columns(self) -> list[str]:
        return [c["label"] for c in self.columns if c.get("type") == "text"]

    def resolve(self, name: str | None, *, numeric: bool = False) -> str | None:
        """把模型给出的字段名对齐到真实列名，避免大小写/简称造成KeyError。"""
        pool = self.number_columns() if numeric else [c["label"] for c in self.columns]
        if not pool:
            return None
        if not name:
            # 数值字段可安全回退到第一个；文本/日期字段必须显式指定或由调用方另选
            return pool[0] if numeric else None
        for label in pool:
            if label == name or label.lower() == str(name).lower():
                return label
        for label in pool:
            if str(name) in label or label in str(name):
                return label
        return pool[0] if numeric else None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    readonly: bool = True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": s.name,
                    "description": s.description,
                    "parameters": s.parameters,
                },
            }
            for s in self._tools.values()
        ]

    def call(self, name: str, arguments: str | dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        spec = self._tools.get(name)
        if not spec:
            raise UnknownTool(f"未注册的工具：{name}")
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ToolError(f"工具参数不是合法 JSON：{name}") from exc
        else:
            args = arguments or {}
        if not isinstance(args, dict):
            raise ToolError(f"工具参数必须是对象：{name}")
        try:
            return spec.handler(ctx, args)
        except (ToolError, UnknownTool):
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"工具 {name} 执行失败：{type(exc).__name__}: {exc}") from exc


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}
