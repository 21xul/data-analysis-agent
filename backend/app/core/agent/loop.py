"""ReAct 主循环：Thought → Action → Observation → … → Final。

以 async generator 逐条产出 SSE 事件；所有数值来自确定性工具，
模型只负责选择工具与组织语言。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.agent.events import event, slim
from app.core.agent.guardrails import Guardrails
from app.core.agent.memory import Memory
from app.core.agent.planner import Planner, build_system
from app.core.config import Settings
from app.core.errors import AppError
from app.infra import dataset_repo
from app.rag.citations import CitationCollector
from app.rag.retriever import as_context, search
from app.tools.registry import ToolContext, ToolRegistry


def parse_conclusions(text: str) -> list[str]:
    lines = str(text or "").replace("**", "").replace("`", "").splitlines()
    out = []
    for line in lines:
        s = line.strip().lstrip("-*•0123456789.、 ").strip()
        if 6 <= len(s) <= 200 and not s.startswith(("#", "<", "```")) and s not in out:
            out.append(s)
    return out[:4]


async def run_agent(
    *,
    question: str,
    ctx: ToolContext,
    registry: ToolRegistry,
    planner: Planner,
    guard: Guardrails,
    conn,
    settings: Settings,
) -> AsyncGenerator[dict[str, Any], None]:
    started = time.monotonic()
    log: list[dict[str, Any]] = []
    citations = CitationCollector()
    memory = Memory()
    final_text = ""

    def emit(kind: str, **kw) -> dict[str, Any]:
        ev = event(kind, **kw)
        log.append(ev)
        return ev

    hits = search(conn, question, top_k=3)
    citations.add_many(hits)
    yield emit("meta", data={
        "mode": planner.mode,
        "model": settings.model if planner.mode == "real" else None,
        "dataset": ctx.dataset_name,
        "tools": registry.names(),
        "max_steps": guard.max_steps,
    })
    yield emit("rag", data={"hits": [{"id": h["id"], "title": h["title"], "score": h["score"]} for h in hits]})

    system = build_system(
        tool_names=registry.names(),
        rag_context=as_context(hits),
        dataset=ctx.dataset_name,
        max_steps=guard.max_steps,
    )
    memory.reset(system, question, as_context(hits))
    signatures: set[str] = set()

    for step in range(guard.max_steps):
        elapsed = time.monotonic() - started
        if elapsed > guard.total_timeout_s:
            yield emit("guardrail", step=step, data={"message": "分析总时长超限，提前结束"})
            break
        try:
            decision = await asyncio.wait_for(
                planner.decide(memory, registry.schemas()), timeout=settings.step_timeout_s
            )
        except asyncio.TimeoutError:
            yield emit("guardrail", step=step, data={"message": "规划器响应超时，使用已有事实收尾"})
            break
        except AppError as exc:
            yield emit("error", step=step, data=exc.as_dict())
            break

        if planner.degraded:
            yield emit("notice", step=step, data={"message": "真实模型不可用，已降级为确定性规划器",
                                                  "reason": planner.degrade_reason})
            planner.degraded = False

        yield emit("thought", step=step, data={"text": decision.thought or "（模型未输出思考，直接给出结论）"})

        if decision.is_final:
            final_text = decision.final or memory.synthesize()
            break

        memory.append_assistant(decision)
        for call in decision.tool_calls[: guard.max_calls_per_step]:
            name = call.get("name") or ""
            try:
                raw_args = guard.check(
                    name=name, arguments=call.get("arguments", "{}"),
                    signatures=signatures, step=step, elapsed=time.monotonic() - started,
                )
                yield emit("action", step=step, data={"tool": name, "arguments": raw_args[:400]})
                result = registry.call(name, raw_args, ctx)
                view = slim(result)
                ref = memory.append_tool(call.get("id", ""), name, view)
                yield emit("observation", step=step, data={"ref": ref, "tool": name, "result": view})
            except AppError as exc:
                yield emit("guardrail", step=step, data={"tool": name, **exc.as_dict()})
                memory.append_tool(call.get("id", ""), name,
                                   {"tool": name, "facts": [f"工具调用被拦截：{exc.message}"]})
    else:
        yield emit("guardrail", step=guard.max_steps, data={"message": "达到最大推理步数，使用已有事实收尾"})

    final_text = final_text or memory.synthesize()
    charts, tables, metrics = [], [], []
    for obs in memory.observations:
        r = obs["result"]
        if r.get("chart"):
            charts.append(r["chart"])
        if r.get("table") and r["table"].get("rows"):
            tables.append({"ref": obs["ref"], **r["table"]})
        metrics.extend(r.get("metrics") or [])

    conclusions = parse_conclusions(final_text)
    payload = {
        "conclusions": conclusions,
        "charts": charts[:3],
        "tables": tables[:3],
        "metrics": metrics[:8],
        "citations": citations.as_list(),
        "steps": len({e["step"] for e in log if e["type"] == "thought"}),
        "mode": planner.mode,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "facts": memory.facts(),
    }
    yield emit("final", data=payload)
    dataset_repo.save_run(conn, ctx.extras.get("dataset_id"), question, log, final_text)
