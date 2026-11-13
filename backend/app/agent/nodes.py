"""LangGraph 节点函数：教程 3.1~3.9 的流程 + v2 的 ReAct 分析分支。

所有节点都是纯函数 ``(state) -> partial_state``；conn / registry 由 graph.py
用闭包注入，节点本身不持有全局状态，方便单测与替换实现。
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from typing import Any

from app.agent.state import AgentState
from app.conf.app_config import app_config
from app.services import cross_check as CC
from app.services import dataset_registry as DR
from app.services import retrieval_service as R
from app.services import sql_service as S
from app.services.meta_knowledge_service import sync_dataset


def _event(node: str, stage: str, **detail: Any) -> dict[str, Any]:
    return {"node": node, "stage": stage, **detail}


_SQL_HINTS = (
    "统计", "总额", "销售额", "销量", "多少", "筛选", "明细", "查数",
    "sql", "字段", "指标", "口径", "取值", "表结构", "排名", "占比",
)
_REACT_HINTS = ("趋势", "异常", "离群", "对比", "比较", "波动", "报告", "概览", "预测", "图表")


def _decide_branch(question: str) -> str:
    q = question.lower()
    if any(k in q for k in _REACT_HINTS):
        return "react"
    if any(k in q for k in _SQL_HINTS):
        return "sql"
    return "sql"


def make_nodes(
    conn: sqlite3.Connection, registry: Any | None = None
) -> dict[str, Callable[[AgentState], dict[str, Any]]]:
    """构造节点集合；registry 为空时 ReAct 分支只记录轨迹、不调用确定性工具。"""

    # ---------------------------------------------------------- 阶段 1
    def extract_keywords(state: AgentState) -> dict[str, Any]:
        kw = R.extract_keywords(state["question"])
        return {
            "keywords": kw,
            "events": [_event("extract_keywords", "理解问题", keywords=kw,
                              original_question=state["question"])],
            "stages": ["理解问题"],
        }

    # ---------------------------------------------------------- 阶段 2（三路并行）
    def recall_columns(state: AgentState) -> dict[str, Any]:
        hits = R.recall_columns(conn, state["question"], state.get("keywords", []))
        return {
            "column_hits": [R.hit_to_dict(h) for h in hits],
            "events": [_event("recall_columns", "并行粗召回",
                              route="vector+structured", count=len(hits),
                              ids=[h.ref_id for h in hits])],
        }

    def recall_metrics(state: AgentState) -> dict[str, Any]:
        hits = R.recall_metrics(conn, state["question"], state.get("keywords", []))
        return {
            "metric_hits": [R.hit_to_dict(h) for h in hits],
            "events": [_event("recall_metrics", "并行粗召回",
                              route="vector+structured", count=len(hits),
                              ids=[h.ref_id for h in hits])],
        }

    def recall_values(state: AgentState) -> dict[str, Any]:
        hits = R.recall_values(conn, state["question"], state.get("keywords", []))
        return {
            "value_hits": [R.hit_to_dict(h) for h in hits],
            "events": [_event("recall_values", "并行粗召回",
                              route="fts5", count=len(hits),
                              values=[h.payload.get("value") for h in hits])],
        }

    # ---------------------------------------------------------- 阶段 3
    def merge_recall(state: AgentState) -> dict[str, Any]:
        # 节点间传递的是 dict（可序列化），这里还原成轻量 hit 对象
        from app.entities.metadata import RecallHit
        def back(items: list[dict[str, Any]]) -> list[RecallHit]:
            return [RecallHit(ref_type=i["ref_type"], ref_id=i["ref_id"],
                              score=float(i.get("score", 0)), source=i.get("source", ""),
                              payload=i.get("payload") or {}) for i in items]
        ctx = R.merge_context(
            conn, back(state.get("column_hits", [])),
            back(state.get("metric_hits", [])), back(state.get("value_hits", [])),
        )
        evidence = {
            "routes": {
                "columns": len(state.get("column_hits", [])),
                "metrics": len(state.get("metric_hits", [])),
                "values": len(state.get("value_hits", [])),
            },
            "tables": [{"id": ti["table"]["id"], "name": ti["table"]["name"],
                        "role": ti["table"]["role"]} for ti in ctx["table_infos"]],
            "columns": [{"id": c["id"], "name": c["name"], "table_id": c["table_id"],
                         "type": c["type"], "role": c["role"]} for c in ctx["columns"]],
            "metrics": [{"id": m["id"], "name": m["name"],
                         "description": m.get("description", "")}
                        for m in ctx["metric_infos"]],
            "values": [{"value": v.get("value"), "column_id": v.get("column_id"),
                        "score": v.get("score")} for v in ctx["value_infos"]],
        }
        return {
            "context": ctx,
            "recall_evidence": evidence,
            "events": [_event("merge_recall", "合并召回信息",
                              tables=len(ctx["table_infos"]), columns=len(ctx["columns"]),
                              metrics=len(ctx["metric_infos"]), values=len(ctx["value_infos"]),
                              evidence=evidence)],
            "stages": ["合并召回信息"],
        }

    def filter_context(state: AgentState) -> dict[str, Any]:
        ctx = R.filter_context(state["context"], state["question"])
        evidence = dict(state.get("recall_evidence") or {})
        evidence["filter"] = ctx["filter"]
        return {
            "context": ctx, "recall_evidence": evidence,
            "events": [_event("filter_context", "精筛上下文", **ctx["filter"])],
            "stages": ["精筛上下文"],
        }

    def enrich_context(state: AgentState) -> dict[str, Any]:
        env = R.enrich(conn)
        return {
            "env": env,
            "events": [_event("enrich_context", "增加额外上下文", **env)],
            "stages": ["增加额外上下文"],
        }

    def resolve_dataset(state: AgentState) -> dict[str, Any]:
        """P1：确认 SQL 执行靶。上传时已自动注册；这里兜底重放并注入 schema。"""
        ds_id = state.get("dataset_id") or ""
        if not ds_id:
            return {
                "dataset_schema": {},
                "events": [_event("resolve_dataset", "解析数据集", registered=False,
                                  note="未指定数据集，SQL 分支只查只读元数据表")],
                "stages": ["解析数据集"],
            }
        try:
            if not DR.is_registered(conn, ds_id):
                DR.ensure_registered(conn, ds_id)
                sync_dataset(conn, ds_id)
            schema = DR.schema_for(conn, ds_id)
        except Exception as exc:  # noqa: BLE001 - 注册失败不阻断整图
            return {
                "dataset_schema": {},
                "events": [_event("resolve_dataset", "解析数据集", registered=False,
                                  error=f"{type(exc).__name__}: {exc}")],
                "stages": ["解析数据集"],
            }
        return {
            "dataset_schema": schema,
            "events": [_event("resolve_dataset", "解析数据集", registered=True,
                              table=schema["table"], rows=schema["row_count"],
                              columns=[c["name"] for c in schema["columns"]])],
            "stages": ["解析数据集"],
        }

    # ---------------------------------------------------------- 阶段 4 分支
    def route_branch(state: AgentState) -> dict[str, Any]:
        branch = state.get("force_branch") or _decide_branch(state["question"])
        return {
            "branch": branch,
            "events": [_event("route_branch", "意图路由", branch=branch)],
            "stages": [f"分支：{branch}"],
        }

    def generate_sql(state: AgentState) -> dict[str, Any]:
        schema = state.get("dataset_schema") or {}
        sql, source = S.generate(state["question"], state.get("context", {}),
                                 state.get("env", {}), schema or None)
        return {
            "sql": sql, "sql_source": source, "corrections": 0,
            "events": [_event("generate_sql", "生成 SQL", source=source, sql=sql,
                              target=schema.get("table", "元数据表"))],
            "stages": ["生成 SQL"],
        }

    def validate_sql(state: AgentState) -> dict[str, Any]:
        ok, error = S.validate(conn, state.get("sql", ""), state.get("dataset_id", ""))
        return {
            "sql_ok": ok, "sql_error": error,
            "events": [_event("validate_sql", "校验 SQL", ok=ok, error=error,
                              attempt=state.get("corrections", 0),
                              whitelist=sorted(S.allowed_tables(conn, state.get("dataset_id", ""))))],
            "stages": ["校验 SQL"],
        }

    def correct_sql(state: AgentState) -> dict[str, Any]:
        attempt = int(state.get("corrections", 0)) + 1
        sql = S.correct(
            state.get("sql", ""), state.get("sql_error", ""),
            state["question"], state.get("context", {}), attempt,
            dataset_id=state.get("dataset_id", ""), conn=conn,
            schema=state.get("dataset_schema") or None,
        )
        return {
            "sql": sql, "corrections": attempt,
            "events": [_event("correct_sql", "校正 SQL", attempt=attempt,
                              reason=state.get("sql_error", ""), sql=sql)],
            "stages": [f"校正 SQL 第 {attempt} 次"],
        }

    def execute_sql(state: AgentState) -> dict[str, Any]:
        ds_id = state.get("dataset_id", "")
        try:
            rows = S.execute(conn, state["sql"], dataset_id=ds_id)
            err = ""
        except (sqlite3.Error, RuntimeError) as exc:
            rows, err = [], str(exc)
        check = CC.check(conn, ds_id, state["sql"], rows) if ds_id else {
            "covered": False, "match": None, "note": "元数据表查询无需交叉校验",
        }
        return {
            "sql_rows": rows, "cross_check": check,
            "events": [_event("execute_sql", "执行 SQL", rows=len(rows), error=err,
                              readonly=bool(ds_id), cross_check=check)],
            "stages": ["执行 SQL"],
        }

    def react_analyze(state: AgentState) -> dict[str, Any]:
        """ReAct 分析分支：复用现有确定性 pandas 工具链，数字仍只由工具产生。"""
        facts: list[str] = []
        if registry is not None and state.get("dataset_id"):
            try:
                from app.bootstrap import build_context
                ctx = build_context(conn, state["dataset_id"])
                result = registry.call("profile", "{}", ctx)
                facts = list(result.get("facts") or [])[:3]
            except Exception as exc:  # noqa: BLE001 - 分支失败不阻断整图
                facts = [f"确定性工具链未产出事实：{type(exc).__name__}"]
        else:
            facts = ["未指定数据集，ReAct 子循环由 SSE 主链路接管（P1 接入）。"]
        return {
            "conclusions": facts,
            "events": [_event("react_analyze", "ReAct 自主分析", facts=len(facts),
                              delegate="app.core.agent.run_agent")],
            "stages": ["ReAct 自主分析"],
        }

    # ---------------------------------------------------------- 汇总
    def synthesize(state: AgentState) -> dict[str, Any]:
        conclusions = list(state.get("conclusions") or [])
        if state.get("branch") == "sql":
            rows = state.get("sql_rows") or []
            if rows:
                head = rows[0]
                parts = "，".join(f"{k}={v}" for k, v in list(head.items())[:3])
                conclusions.append(f"只读查询返回 {len(rows)} 行，首行：{parts}。")
            elif state.get("sql_error"):
                conclusions.append(f"SQL 未通过校验，已按护栏终止：{state['sql_error']}")
            cc = state.get("cross_check") or {}
            if cc.get("covered"):
                conclusions.append(
                    f"交叉校验{('一致' if cc.get('match') else '不一致')}："
                    f"SQL={cc.get('sql_value')} / pandas={cc.get('pandas_value')}。"
                )
            elif cc.get("note"):
                conclusions.append(f"交叉校验说明：{cc['note']}")
        ctx = state.get("context", {})
        citations = [
            {"kind": kind, "id": cid}
            for kind, ids in (ctx.get("recall") or {}).items()
            for cid in (ids or [])
        ][:8]
        return {
            "conclusions": conclusions[:4], "citations": citations, "charts": [],
            "events": [_event("synthesize", "汇总结论", conclusions=len(conclusions[:4]))],
            "stages": ["汇总结论"],
        }

    def finalize(state: AgentState) -> dict[str, Any]:
        final = {
            "question": state["question"],
            "branch": state.get("branch"),
            "keywords": state.get("keywords", []),
            "sql": state.get("sql", ""),
            "sql_source": state.get("sql_source", ""),
            "sql_ok": state.get("sql_ok", False),
            "sql_rows": state.get("sql_rows", []),
            "sql_error": state.get("sql_error", ""),
            "corrections": state.get("corrections", 0),
            "dataset_schema": state.get("dataset_schema", {}),
            "cross_check": state.get("cross_check", {}),
            "recall_evidence": state.get("recall_evidence", {}),
            "conclusions": state.get("conclusions", []),
            "charts": state.get("charts", []),
            "citations": state.get("citations", []),
            "env": state.get("env", {}),
            # finalize 自身刚 append 的事件尚未进入 state，这里补进最终载荷保证轨迹闭合
            "events": list(state.get("events", [])) + [_event("finalize", "完成")],
            "stages": list(state.get("stages", [])) + ["完成"],
            "max_sql_corrections": app_config.agent.max_sql_corrections,
        }
        return {"final": final, "events": [_event("finalize", "完成")], "stages": ["完成"]}

    nodes: dict[str, Callable[[AgentState], dict[str, Any]]] = {
        "extract_keywords": extract_keywords,
        "recall_columns": recall_columns,
        "recall_metrics": recall_metrics,
        "recall_values": recall_values,
        "merge_recall": merge_recall,
        "filter_context": filter_context,
        "enrich_context": enrich_context,
        "resolve_dataset": resolve_dataset,
        "route_branch": route_branch,
        "generate_sql": generate_sql,
        "validate_sql": validate_sql,
        "correct_sql": correct_sql,
        "execute_sql": execute_sql,
        "react_analyze": react_analyze,
        "synthesize": synthesize,
        "finalize": finalize,
    }

    # LangGraph 的三路召回在线程池里并行执行，而 sqlite3.Connection 不是线程安全的
    # （即使 check_same_thread=False，并发 execute 也会串扰 cursor）。单文件 SQLite
    # 下用一把锁串行化连接访问；日后换托管库 / 每路独立连接时去掉即可恢复真并行。
    lock = threading.Lock()

    def serialized(fn: Callable[[AgentState], dict[str, Any]]):
        def wrapped(state: AgentState) -> dict[str, Any]:
            with lock:
                return fn(state)
        return wrapped

    return {name: serialized(fn) for name, fn in nodes.items()}


__all__ = ["make_nodes", "_event", "_decide_branch"]
