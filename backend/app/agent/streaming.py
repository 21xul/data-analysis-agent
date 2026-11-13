"""P1：把 LangGraph 的节点执行过程变成可消费的事件流。

``graph.stream(stream_mode="updates")`` 每完成一个 superstep 产出一次增量状态，
我们从中抽出节点自己写的 ``events``，逐条转成 SSE 事件；``finalize`` 的 ``final``
载荷在流末单独发一次。这样前端能实时看到「理解问题 → 三路召回 → 校验 → 执行」，
而不是等到整图跑完才拿到一坨轨迹。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from typing import Any

from app.agent.graph import build_graph
from app.agent.state import AgentState
from app.conf.app_config import effective_mode

# 节点内部有一把 per-graph 锁；这里再加一把跨请求锁，避免并发请求共用同一个
# sqlite3.Connection 时互相串扰（C 路线原型为单用户，串行化最稳妥）。
_GRAPH_LOCK = threading.RLock()


def iter_events(
    conn: sqlite3.Connection,
    question: str,
    *,
    dataset_id: str = "",
    registry: Any | None = None,
    force_branch: str = "",
    request_id: str = "",
) -> Iterator[dict[str, Any]]:
    graph = build_graph(conn, registry)
    initial: AgentState = {
        "request_id": request_id,
        "question": question,
        "dataset_id": dataset_id,
        "force_branch": force_branch,
        "events": [],
        "stages": [],
    }
    started = time.perf_counter()
    yield {
        "type": "meta", "id": "m0", "step": 0, "ts": 0,
        "data": {"engine": "langgraph", "mode": effective_mode(),
                 "question": question, "dataset_id": dataset_id,
                 "request_id": request_id,
                 "nodes": sorted(graph.nodes.keys())},
    }

    seq = 0
    final: dict[str, Any] | None = None
    with _GRAPH_LOCK:
        for update in graph.stream(
            initial, config={"recursion_limit": 32}, stream_mode="updates"
        ):
            if not isinstance(update, dict):
                continue
            for node, partial in update.items():
                if not isinstance(partial, dict):
                    continue
                if isinstance(partial.get("final"), dict):
                    final = partial["final"]
                for ev in partial.get("events") or []:
                    seq += 1
                    detail = {k: v for k, v in ev.items()
                              if k not in ("node", "stage")}
                    # 完整召回证据放在 final 里发，逐节点事件只带计数，避免帧过大
                    if "evidence" in detail:
                        evi = detail["evidence"] or {}
                        detail["evidence"] = {"routes": evi.get("routes", {})}
                    yield {
                        "type": "node", "id": f"n{seq}", "step": seq,
                        "ts": round((time.perf_counter() - started) * 1000),
                        "data": {"node": ev.get("node", node),
                                 "stage": ev.get("stage", node),
                                 "detail": detail},
                    }

    yield {
        "type": "final", "id": "f0", "step": seq + 1,
        "ts": round((time.perf_counter() - started) * 1000),
        "data": final or {"question": question, "error": "图未产出 final 载荷"},
    }


__all__ = ["iter_events"]
