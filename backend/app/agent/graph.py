"""查询期主线：LangGraph 状态图（教程第 2 章流程图的代码对应物）。

    START → extract_keywords
          → ┌ recall_columns ┐
            ├ recall_metrics ├→ merge_recall → filter_context → enrich_context
            └ recall_values  ┘                                      ↓
                                                resolve_dataset（P1：只读执行靶）
                                                                    ↓
                                                              route_branch
                                        ┌────────── sql ──────────┴─ react ─────────┐
                                        ↓                                            ↓
              generate_sql → validate_sql ─(ok)→ execute_sql ─┐        react_analyze
                                  └─(fail, <2 次)→ correct_sql ┘              │
                                                    ↑_______________________│
                                                    ↓
                                       synthesize → finalize → END

设计取舍：固定前置检索管线（保证上下文质量）+ 中段分支（SQL 闭环 / ReAct 自主）
+ 后置汇总，既复刻教程的多阶段可观测性，又保留 v2 的自我推理决策。
"""
from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import make_nodes
from app.agent.state import AgentState
from app.conf.app_config import app_config


def _branch_router(state: AgentState) -> str:
    return "generate_sql" if state.get("branch") == "sql" else "react_analyze"


def _validate_router(state: AgentState) -> str:
    if state.get("sql_ok"):
        return "execute_sql"
    if int(state.get("corrections", 0)) < app_config.agent.max_sql_corrections:
        return "correct_sql"
    return "synthesize"


def build_graph(conn: sqlite3.Connection, registry: Any | None = None):
    nodes = make_nodes(conn, registry)
    builder = StateGraph(AgentState)
    for name, fn in nodes.items():
        builder.add_node(name, fn)

    builder.add_edge(START, "extract_keywords")
    for recall in ("recall_columns", "recall_metrics", "recall_values"):
        builder.add_edge("extract_keywords", recall)
        builder.add_edge(recall, "merge_recall")

    builder.add_edge("merge_recall", "filter_context")
    builder.add_edge("filter_context", "enrich_context")
    builder.add_edge("enrich_context", "resolve_dataset")   # P1：确认只读执行靶
    builder.add_edge("resolve_dataset", "route_branch")

    builder.add_conditional_edges(
        "route_branch", _branch_router,
        {"generate_sql": "generate_sql", "react_analyze": "react_analyze"},
    )
    builder.add_edge("generate_sql", "validate_sql")
    builder.add_conditional_edges(
        "validate_sql", _validate_router,
        {"execute_sql": "execute_sql", "correct_sql": "correct_sql",
         "synthesize": "synthesize"},
    )
    builder.add_edge("correct_sql", "validate_sql")
    builder.add_edge("execute_sql", "synthesize")
    builder.add_edge("react_analyze", "synthesize")
    builder.add_edge("synthesize", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


def run(
    conn: sqlite3.Connection,
    question: str,
    *,
    dataset_id: str = "",
    registry: Any | None = None,
    force_branch: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    """同步执行整图并返回 final 载荷；SSE 接入时改为 graph.stream 逐节点产出。"""
    graph = build_graph(conn, registry)
    initial: AgentState = {
        "request_id": request_id,
        "question": question,
        "dataset_id": dataset_id,
        "force_branch": force_branch,
        "events": [],
        "stages": [],
    }
    state = graph.invoke(initial, config={"recursion_limit": 32})
    return state["final"]


__all__ = ["build_graph", "run"]
