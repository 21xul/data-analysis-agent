"""SQL 闭环：生成 → 白名单校验 + EXPLAIN → 纠错 → 只读执行（教程 3.6~3.9）。

P1 的变化：执行靶从「只读元数据表」扩展到**已注册的数据集物理表** ``ds_<id>``。
模型生成的 SQL 只能引用 ``READABLE_TABLES`` 或 ``dataset_tables`` 中登记过的表，
且执行时另开 ``mode=ro`` 连接；结果再交给 cross_check.py 与 pandas 交叉校验。
绝不在可写业务库上直接跑模型生成的 SQL。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from app.clients.llm_client import build_chat_model
from app.conf.app_config import app_config
from app.prompt.loader import load
from app.services import dataset_registry as DR
from app.services import retrieval_service as R

READABLE_TABLES = {
    "table_info", "column_info", "metric_info", "column_metric",
    "value_info", "meta_vectors", "value_fts",
}
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|"
    r"trigger|vacuum|reindex|load_extension)\b", re.I,
)
_FROM_JOIN = re.compile(r"\b(?:from|join)\s+[\"'`]?([A-Za-z_][A-Za-z0-9_]*)", re.I)


def allowed_tables(conn: sqlite3.Connection, dataset_id: str = "") -> set[str]:
    tables = set(READABLE_TABLES)
    tables |= {t.lower() for t in DR.registered_tables(conn, dataset_id)}
    return tables


def validate(conn: sqlite3.Connection, sql: str, dataset_id: str = "") -> tuple[bool, str]:
    s = str(sql or "").strip().rstrip(";").strip()
    if not s:
        return False, "SQL 为空"
    if not re.match(r"^(select|with)\b", s, re.I):
        return False, "只允许 SELECT / WITH 开头的只读语句"
    if ";" in s:
        return False, "禁止多语句"
    if "--" in s or "/*" in s or "*/" in s:
        return False, "禁止 SQL 注释"
    if _FORBIDDEN.search(s):
        return False, "包含被禁止的关键字（DDL / DML / PRAGMA / ATTACH）"
    tables = [t.lower() for t in _FROM_JOIN.findall(s)]
    if not tables:
        return False, "未识别到 FROM 子句"
    bad = [t for t in tables if t not in allowed_tables(conn, dataset_id)]
    if bad:
        return False, "表不在只读白名单：" + ", ".join(bad)
    limit = re.search(r"\blimit\s+(\d+)", s, re.I)
    if limit and int(limit.group(1)) > app_config.agent.max_rows:
        return False, f"LIMIT 超过上限 {app_config.agent.max_rows}"
    try:
        conn.execute("EXPLAIN QUERY PLAN " + s)
    except sqlite3.Error as exc:
        return False, f"EXPLAIN 校验失败：{exc}"
    return True, ""


def _mock_generate(question: str, ctx: dict[str, Any], env: dict[str, str]) -> str:
    """无数据集时的元数据画像查询，用于验证闭环（不产生业务数字）。"""
    q = question.lower()
    if any(k in q for k in ("字段", "列", "column")):
        return "SELECT role, COUNT(*) AS cnt FROM column_info GROUP BY role LIMIT 50"
    if any(k in q for k in ("指标", "metric", "口径")):
        return "SELECT id, name, description FROM metric_info LIMIT 50"
    if any(k in q for k in ("取值", "字段值", "值")):
        return "SELECT column_id, COUNT(*) AS cnt FROM value_info GROUP BY column_id LIMIT 50"
    return "SELECT role, COUNT(*) AS cnt FROM table_info GROUP BY role LIMIT 50"


def _where_from_question(question: str, ctx: dict[str, Any], columns: list[dict]) -> str:
    """把自然语言里的维度取值映射到真实列（先走召回证据，再走 schema 样例值）。"""
    names = {c["name"] for c in columns}
    candidates: list[tuple[str, str]] = []
    for vi in ctx.get("value_infos") or []:
        v = str(vi.get("value") or "")
        cid = str(vi.get("column_id") or "")
        if v and cid.startswith("dataset:"):
            candidates.append((cid.rsplit(".", 1)[-1], v))
    for c in columns:
        for v in c.get("samples") or []:
            candidates.append((c["name"], str(v)))
    for col, value in candidates:
        if col in names and len(value) >= 2 and value in question:
            return " WHERE " + DR.quote(col) + " = '" + value.replace("'", "''") + "'"
    return ""


def _mock_generate_dataset(
    question: str, ctx: dict[str, Any], schema: dict[str, Any]
) -> str:
    """确定性模板：针对已注册数据集生成聚合 SQL，供 pandas 交叉校验。"""
    table = schema["table"]
    columns = schema["columns"]
    nums = [c for c in columns if c["type"] == "number"]
    where = _where_from_question(question, ctx, columns)
    limit = min(app_config.agent.max_rows, 50)
    q = question
    if not nums:
        return f"SELECT * FROM {table}{where} LIMIT {limit}"
    col = DR.quote(nums[0]["name"])
    if any(k in q for k in ("明细", "记录", "行数据", "清单", "前 10", "前10")):
        return f"SELECT * FROM {table}{where} LIMIT {limit}"
    if any(k in q for k in ("平均", "均值", "人均")):
        agg = f"AVG({col})"
    elif any(k in q for k in ("最大", "最高", "峰值")):
        agg = f"MAX({col})"
    elif any(k in q for k in ("最小", "最低")):
        agg = f"MIN({col})"
    elif any(k in q for k in ("条数", "多少条", "记录数", "行数", "笔数")):
        agg = "COUNT(*)"
    else:
        agg = f"SUM({col})"
    return f"SELECT {agg} AS 结果 FROM {table}{where} LIMIT 1"


def generate(
    question: str,
    ctx: dict[str, Any],
    env: dict[str, str],
    schema: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """返回 (sql, source)。真模型不可用时自动回退确定性模板。"""
    model = build_chat_model()
    if model is None:
        sql = (_mock_generate_dataset(question, ctx, schema) if schema
               else _mock_generate(question, ctx, env))
        return sql, "mock"
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        dataset_schema = R.as_yaml(schema) if schema else "（本次未指定数据集）"
        prompt = load(
            "sql_generate",
            dialect=env.get("dialect", "sqlite"), db_version=env.get("db_version", ""),
            now=env.get("now", ""), question=question,
            table_infos=R.as_yaml(ctx.get("table_infos", [])),
            metric_infos=R.as_yaml(ctx.get("metric_infos", [])),
            value_infos=R.as_yaml(ctx.get("value_infos", [])),
            dataset_schema=dataset_schema,
            max_rows=app_config.agent.max_rows,
        )
        resp = model.invoke([SystemMessage(content="只输出 SQL。"), HumanMessage(content=prompt)])
        sql = str(resp.content or "").strip().strip("`").removeprefix("sql").strip()
        return sql, "llm"
    except Exception:  # noqa: BLE001 - 模型不可用/超时一律回退，不让编排中断
        sql = (_mock_generate_dataset(question, ctx, schema) if schema
               else _mock_generate(question, ctx, env))
        return sql, "mock-fallback"


def correct(
    sql: str, error: str, question: str, ctx: dict[str, Any], attempt: int,
    *, dataset_id: str = "", conn: sqlite3.Connection | None = None,
    schema: dict[str, Any] | None = None,
) -> str:
    """规则纠错；接真模型后改为 sql_correct.md 模板 + 报错上下文。"""
    s = str(sql or "").strip()
    s = re.sub(r"--[^\n]*", "", s)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = s.rstrip(";").strip()
    whitelist = allowed_tables(conn, dataset_id) if conn is not None else set(READABLE_TABLES)
    fallback = schema["table"] if schema else "table_info"
    tables = [t.lower() for t in _FROM_JOIN.findall(s)]
    for t in tables:
        if t not in whitelist:
            s = re.sub(rf"\b{t}\b", fallback, s, flags=re.I)
    if not re.search(r"\blimit\s+\d+", s, re.I):
        s += f" LIMIT {min(app_config.agent.max_rows, 50)}"
    if not re.match(r"^(select|with)\b", s, re.I):
        s = (_mock_generate_dataset(question, ctx, schema) if schema
             else _mock_generate(question, ctx, {}))
    return s


def execute(
    conn: sqlite3.Connection, sql: str, *, dataset_id: str = ""
) -> list[dict[str, Any]]:
    """模型生成的 SQL 一律走 mode=ro 连接；元数据查询可沿用原连接。"""
    if dataset_id:
        ro = DR.readonly_connection(conn)
        try:
            rows = ro.execute(sql).fetchall()
            return [dict(r) for r in rows[: app_config.agent.max_rows]]
        finally:
            ro.close()
    rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows[: app_config.agent.max_rows]]


__all__ = [
    "READABLE_TABLES", "allowed_tables", "validate", "generate", "correct", "execute",
]
