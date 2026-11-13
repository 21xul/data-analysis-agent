"""LangGraph 编排入口。

- ``POST /graph/runs``        P0 同步契约：一次返回完整节点轨迹（保留给回归/对照）
- ``POST /graph/runs/stream`` P1 逐节点 SSE：meta → node×N → final → done

SSE 用「后台线程跑同步 graph.stream + asyncio.Queue 转发」，不阻塞事件循环；
节点函数是同步的（pandas / sqlite3），也不需要强行改成 async 节点。
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.agent.graph import run
from app.agent.streaming import iter_events
from app.schemas.agent import GraphRunRequest

router = APIRouter(tags=["graph"])

_SENTINEL = object()


def _sse(ev: dict[str, Any]) -> str:
    return f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"


@router.post("/graph/runs")
async def graph_runs(body: GraphRunRequest, request: Request) -> dict:
    conn = request.app.state.db
    final = await run_in_threadpool(
        run, conn, body.question,
        dataset_id=body.dataset_id,
        registry=request.app.state.registry,
        force_branch=body.force_branch,
        request_id=request.headers.get("x-request-id", ""),
    )
    return {"data": final}


@router.post("/graph/runs/stream")
async def graph_runs_stream(body: GraphRunRequest, request: Request) -> StreamingResponse:
    conn = request.app.state.db
    registry = request.app.state.registry
    request_id = request.headers.get("x-request-id", "")
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker() -> None:
        try:
            for ev in iter_events(
                conn, body.question,
                dataset_id=body.dataset_id,
                registry=registry,
                force_branch=body.force_branch,
                request_id=request_id,
            ):
                loop.call_soon_threadsafe(queue.put_nowait, ev)
        except Exception as exc:  # noqa: BLE001 - 流内不允许未捕获异常直接断连
            loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "error", "step": -1, "ts": 0,
                "data": {"code": "graph_stream_error",
                         "message": f"{type(exc).__name__}: {exc}"},
            })
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    threading.Thread(target=worker, name="langgraph-stream", daemon=True).start()

    async def stream():
        while True:
            ev = await queue.get()
            if ev is _SENTINEL:
                break
            yield _sse(ev)
        yield _sse({"type": "done", "step": -1, "ts": 0, "data": {}})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )
