"""Agent 运行入口：SSE 事件流。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.bootstrap import build_context
from app.core.agent.guardrails import Guardrails
from app.core.agent.loop import run_agent
from app.core.agent.planner import Planner
from app.core.config import settings
from app.core.errors import AppError, DatasetNotFound
from app.infra.llm_client import LLMClient
from app.schemas.agent import RunRequest

router = APIRouter(tags=["agent"])


def _sse(ev: dict) -> str:
    return f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"


@router.post("/runs")
async def create_run(body: RunRequest, request: Request) -> StreamingResponse:
    conn = request.app.state.db
    try:
        ctx = build_context(conn, body.dataset_id)
    except DatasetNotFound as exc:
        raise HTTPException(404, exc.message) from exc
    ctx.extras["question"] = body.question

    registry = request.app.state.registry
    planner = Planner(LLMClient(settings), settings.llm_mode)
    guard = Guardrails(
        allowed=set(registry.names()),
        max_steps=settings.max_steps,
        total_timeout_s=settings.total_timeout_s,
    )

    async def stream():
        try:
            async for ev in run_agent(
                question=body.question, ctx=ctx, registry=registry,
                planner=planner, guard=guard, conn=conn, settings=settings,
            ):
                yield _sse(ev)
            yield _sse({"type": "done", "step": -1, "ts": 0, "data": {}})
        except AppError as exc:
            yield _sse({"type": "error", "step": -1, "ts": 0, "data": exc.as_dict()})
        except Exception as exc:  # noqa: BLE001 - 事件流内不允许未捕获异常中断
            yield _sse({"type": "error", "step": -1, "ts": 0,
                        "data": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
