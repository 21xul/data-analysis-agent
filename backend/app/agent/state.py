"""LangGraph 全局状态（教程第 2 章「架构图与代码目录一一对应」）。

每个图节点只写自己负责的字段；``events`` / ``stages`` 用 reducer 累加，
这样三路并行召回节点同时写轨迹也不会互相覆盖。
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    # 输入
    request_id: str
    question: str
    dataset_id: str
    force_branch: str                 # 测试/调试可强制 sql | react

    # 阶段 1：理解问题
    keywords: list[str]

    # 阶段 2：三路并行粗召回
    column_hits: list[dict[str, Any]]
    metric_hits: list[dict[str, Any]]
    value_hits: list[dict[str, Any]]

    # 阶段 3：合并 / 精筛 / 环境上下文
    context: dict[str, Any]
    env: dict[str, str]
    recall_evidence: dict[str, Any]        # P1：三路召回证据（前端视图直接消费）

    # 阶段 4：分支与 SQL 闭环
    branch: str
    dataset_schema: dict[str, Any]         # P1：已注册数据集的真实执行靶
    sql: str
    sql_source: str
    sql_ok: bool
    sql_error: str
    corrections: int
    sql_rows: list[dict[str, Any]]
    cross_check: dict[str, Any]            # P1：SQL ↔ pandas 交叉校验结论

    # 汇总
    conclusions: list[str]
    charts: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    final: dict[str, Any]

    # 可观测性
    events: Annotated[list[dict[str, Any]], operator.add]
    stages: Annotated[list[str], operator.add]


__all__ = ["AgentState"]
