"""示例 MCP server：仅实现 initialize / tools/list / tools/call。

纯标准库，无外部依赖。生产环境可替换为任意符合 MCP 协议的外部工具服务。
"""
from __future__ import annotations

import json
import sys

TOOLS = [{
    "name": "describe_dataset",
    "description": "返回当前分析会话的数据集摘要信息（演示用外部工具）。",
    "inputSchema": {"type": "object", "properties": {}},
}]


def reply(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid, method = req.get("id"), req.get("method")
        if rid is None:
            continue
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "insight-demo-server", "version": "0.1.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = (req.get("params") or {}).get("name")
            if name != "describe_dataset":
                reply({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown tool"}})
                continue
            result = {"content": [{"type": "text", "text": "外部 MCP 工具已连接：当前会话使用本地 SQLite 数据集。"}]}
        else:
            reply({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})
            continue
        reply({"jsonrpc": "2.0", "id": rid, "result": result})


if __name__ == "__main__":
    main()
