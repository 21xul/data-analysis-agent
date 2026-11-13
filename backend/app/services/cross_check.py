"""P1：SQL 结果 ↔ pandas 确定性结果交叉校验。

模型生成的 SQL 不是可信数字来源。这里对**可归约的标量聚合**用 pandas 从原始
数据集独立重算一遍，与 SQL 返回值比对；覆盖不了的查询（JOIN / GROUP BY / 嵌套）
如实标注 ``covered=false``，绝不假装校验通过。

数字仍然只由确定性计算产生：SQL 只是取数路径，最终是否采信由这里决定。
"""
from __future__ import annotations

import math
import re
import sqlite3
from typing import Any

import pandas as pd

from app.infra import dataset_repo
from app.services import dataset_registry as DR

_SELECT = re.compile(
    r"^\s*select\s+(.+?)\s+from\s+([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$", re.I | re.S
)
_AGG = re.compile(
    r"^(sum|avg|min|max|count)\s*\(\s*(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*)|(\*))\s*\)$",
    re.I,
)
_WHERE = re.compile(
    r"\bwhere\s+(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))\s*=\s*'([^']*)'", re.I,
)


def spec_from_sql(sql: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """把一条简单聚合 SQL 归约成 pandas 可重算的规格；复杂查询返回 None。"""
    m = _SELECT.match(str(sql or ""))
    if not m:
        return None
    expr, table, tail = m.group(1).strip(), m.group(2), m.group(3)
    if table.lower() != str(schema.get("table", "")).lower():
        return None
    low = tail.lower()
    if "join" in low or "group by" in low or "union" in low or "select" in low:
        return None
    # 只接受单一聚合表达式（可带 AS 别名）
    expr = re.sub(r"\s+as\s+[\"`'\[]?[\w\u4e00-\u9fa5]+[\"`'\]]?\s*$", "", expr, flags=re.I).strip()
    a = _AGG.match(expr)
    if not a:
        return None
    kind = a.group(1).lower()
    column = a.group(2) or a.group(3) or ("*" if a.group(4) else "")
    known = {c["name"] for c in schema.get("columns", [])}
    if column and column != "*" and column not in known:
        return None
    where: dict[str, str] | None = None
    w = _WHERE.search(tail)
    if w:
        col = w.group(1) or w.group(2)
        if col in known:
            where = {"column": col, "value": w.group(3)}
    return {"kind": kind, "column": column, "where": where}


def check(
    conn: sqlite3.Connection,
    dataset_id: str,
    sql: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """返回 {covered, match, sql_value, pandas_value, method, note}。"""
    base = {
        "covered": False, "match": None, "sql_value": None, "pandas_value": None,
        "method": "pandas vs sql", "note": "", "dataset_id": dataset_id,
    }
    if not dataset_id:
        base["note"] = "未指定数据集，跳过交叉校验"
        return base
    try:
        schema = DR.schema_for(conn, dataset_id)
        ds = dataset_repo.get(conn, dataset_id)
    except Exception as exc:  # noqa: BLE001
        base["note"] = f"数据集不可读：{type(exc).__name__}"
        return base

    spec = spec_from_sql(sql, schema)
    if spec is None:
        base["note"] = "SQL 含 JOIN / GROUP BY / 非聚合表达式，超出标量交叉校验范围"
        return base

    df = pd.DataFrame(ds.get("rows") or [])
    if df.empty:
        base["note"] = "数据集为空"
        return base
    w = spec.get("where")
    if w and w["column"] in df.columns:
        df = df[df[w["column"]].astype(str) == str(w["value"])]

    kind, col = spec["kind"], spec["column"]
    try:
        if col == "*" or kind == "count":
            series = None
            value: float | int = len(df)
        else:
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            value = {
                "sum": lambda s: float(s.sum()),
                "avg": lambda s: float(s.mean()),
                "min": lambda s: float(s.min()),
                "max": lambda s: float(s.max()),
                "count": lambda s: int(s.count()),
            }[kind](series)
    except (KeyError, ValueError, TypeError) as exc:
        base["note"] = f"pandas 重算失败：{type(exc).__name__}"
        return base

    sql_value: float | None = None
    if rows:
        first = list(rows[0].values())
        for v in first:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                sql_value = float(v)
                break
    base.update({
        "covered": True,
        "sql_value": sql_value,
        "pandas_value": round(float(value), 4),
        "spec": spec,
        "filter_rows": int(len(df)),
    })
    if sql_value is None:
        base["match"] = None
        base["note"] = "SQL 未返回数值列"
    else:
        base["match"] = bool(
            math.isclose(sql_value, float(value), rel_tol=1e-6, abs_tol=0.01)
        )
        base["note"] = (
            f"{kind.upper()}({col or '*'}) 由 pandas 独立重算"
            + (f"，筛选 {w['column']}={w['value']} 命中 {len(df)} 行" if w else "")
            + ("，与 SQL 一致" if base["match"] else "，与 SQL 不一致（需人工复核）")
        )
    return base


__all__ = ["spec_from_sql", "check"]
