"""最小 MCP stdio 客户端（JSON-RPC 2.0，换行分隔消息）。

使用同步 subprocess 而非 asyncio：工具 handler 在 FastAPI 的工作线程里同步调用，
避免与运行中的事件循环冲突。不依赖第三方 MCP 框架。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.errors import MCPError

SERVER = Path(__file__).resolve().parent / "servers" / "echo_server.py"


class StdioMCPClient:
    def __init__(self, server: Path | None = None, timeout: float = 5.0):
        self.server = server or SERVER
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._seq = 0

    def start(self) -> None:
        if not self.server.exists():
            raise MCPError(f"MCP server 不存在：{self.server}")
        self._proc = subprocess.Popen(
            [sys.executable, str(self.server)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
        )
        self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "insight-agent", "version": "0.1.0"},
        })

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise MCPError("MCP server 未启动")
        self._seq += 1
        rid = self._seq
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise MCPError("MCP server 已关闭连接")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") != rid:
                continue  # 跳过通知类消息
            if "error" in msg:
                raise MCPError(f"MCP 错误：{msg['error']}")
            return msg.get("result") or {}

    def list_tools(self) -> list[dict[str, Any]]:
        return (self._request("tools/list", {}) or {}).get("tools") or []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.close()
        if self._proc:
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
