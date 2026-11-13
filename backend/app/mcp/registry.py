"""把 MCP server 的工具按白名单包装进 ToolRegistry，并做审计。

审计只记录工具名、耗时与成功与否，不记录参数内容或任何凭据。
"""
from __future__ import annotations

import time
from typing import Any

from app.core.errors import MCPError, ToolError
from app.tools.registry import ToolRegistry, ToolSpec

ALLOWED = {"describe_dataset"}


def register_mcp_tools(registry: ToolRegistry, client) -> list[str]:
    client.start()
    loaded: list[str] = []
    for t in client.list_tools():
        name = str(t.get("name") or "")
        if name not in ALLOWED:
            continue

        def make_handler(tool_name: str):
            def handler(ctx, args) -> dict[str, Any]:
                started = time.monotonic()
                try:
                    result = client.call_tool(tool_name, args)
                except MCPError as exc:
                    raise ToolError(f"MCP 工具 {tool_name} 调用失败：{exc}") from exc
                elapsed = round((time.monotonic() - started) * 1000)
                content = result.get("content") or []
                text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
                return {
                    "tool": f"mcp__{tool_name}",
                    "facts": [text[:400] or f"MCP 工具 {tool_name} 已执行。"],
                    "metrics": [{"k": "MCP 耗时", "v": f"{elapsed} ms"}],
                }
            return handler

        spec = ToolSpec(
            name=f"mcp__{name}",
            description=str(t.get("description") or f"MCP 工具 {name}"),
            parameters=t.get("inputSchema") or {"type": "object", "properties": {}},
            handler=make_handler(name),
            readonly=True,
        )
        registry.register(spec)
        loaded.append(spec.name)
    return loaded
