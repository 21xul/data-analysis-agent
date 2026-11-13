"""P1：把上传数据集注册成只读 SQLite 物理表（SQL 分支的真实执行靶）。

教程第 2 章的执行靶是固定数仓；v2 是「用户上传表格」，所以这里做一层
**注册表**：每个数据集落成一张 ``ds_<token>`` 表，登记到 ``dataset_tables``。

三道边界（都不能省）：
1. 表名由服务端按 dataset_id 派生，模型不能自己指定表名；
2. SQL 白名单只认注册表里登记过的 ``ds_`` 表（见 sql_service.validate）；
3. 执行时另开 ``mode=ro`` 只读连接，即使白名单被绕过也写不了库。

数据行只进物理表，不进向量库 / FTS5；后者仍只索引口径与元数据。
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.infra import dataset_repo

PREFIX = "ds_"
SAFE_ID = re.compile(r"^[A-Za-z0-9_]{1,48}$")
_MAX_ROWS = 20000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def table_name(dataset_id: str) -> str:
    """稳定派生表名：合法 id 直接拼接，其余取哈希，杜绝标识符注入。"""
    if SAFE_ID.match(dataset_id or ""):
        return PREFIX + dataset_id
    digest = hashlib.sha256(str(dataset_id).encode("utf-8")).hexdigest()[:20]
    return PREFIX + digest


def quote(identifier: str) -> str:
    """SQLite 标识符引用；中文列名含双引号时按 SQL 规则转义。"""
    return '"' + str(identifier).replace('"', '""') + '"'


def _column_type(col: dict[str, Any]) -> str:
    return "REAL" if col.get("type") == "number" else "TEXT"


def _value(raw: Any, col: dict[str, Any]) -> Any:
    if raw is None:
        return None
    if col.get("type") == "number":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False)
    return str(raw)


def is_registered(conn: sqlite3.Connection, dataset_id: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM dataset_tables WHERE dataset_id = ?", (dataset_id,)
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def registered_tables(conn: sqlite3.Connection, dataset_id: str = "") -> set[str]:
    """供 SQL 白名单使用；dataset_id 非空时只放开该数据集自己的表。"""
    try:
        if dataset_id:
            rows = conn.execute(
                "SELECT table_name FROM dataset_tables WHERE dataset_id = ?", (dataset_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT table_name FROM dataset_tables").fetchall()
        return {str(r["table_name"]) for r in rows}
    except sqlite3.OperationalError:
        return set()


def ensure_registered(conn: sqlite3.Connection, dataset_id: str) -> dict[str, Any]:
    """幂等注册：重建物理表并覆盖登记信息，返回 schema 描述。"""
    ds = dataset_repo.get(conn, dataset_id)
    name = table_name(dataset_id)
    columns = [c for c in (ds.get("columns") or []) if str(c.get("label") or "").strip()]
    if not columns:
        raise ValueError(f"数据集 {dataset_id} 没有可用字段")

    rows = (ds.get("rows") or [])[:_MAX_ROWS]
    defs = ", ".join(f"{quote(c['label'])} {_column_type(c)}" for c in columns)
    conn.execute(f"DROP TABLE IF EXISTS {quote(name)}")
    conn.execute(f"CREATE TABLE {quote(name)} ({defs})")

    labels = [c["label"] for c in columns]
    placeholders = ", ".join("?" for _ in labels)
    insert_sql = (
        f"INSERT INTO {quote(name)} "
        f"({', '.join(quote(x) for x in labels)}) VALUES ({placeholders})"
    )
    conn.executemany(insert_sql, [
        tuple(_value(row.get(label), col) for label, col in zip(labels, columns))
        for row in rows
    ])

    # 文本列的高频取值为「候选值映射」提供素材；不进向量库，也不当数据行索引
    samples_by_label: dict[str, list[str]] = {}
    for c in columns:
        label = c["label"]
        if c.get("type") == "number":
            continue
        seen: list[str] = []
        for row in rows:
            v = row.get(label)
            if v is None:
                continue
            s = str(v)
            if s not in seen:
                seen.append(s)
            if len(seen) >= 8:
                break
        samples_by_label[label] = seen

    schema = {
        "dataset_id": dataset_id,
        "dataset_name": ds.get("name") or "未命名数据集",
        "table": name,
        "columns": [
            {"name": c["label"], "type": c.get("type", "text"),
             "sql_type": _column_type(c), "quoted": quote(c["label"]),
             "samples": samples_by_label.get(c["label"], [])}
            for c in columns
        ],
        "row_count": len(rows),
    }
    conn.execute(
        "INSERT INTO dataset_tables (dataset_id, table_name, columns, row_count, created_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(dataset_id) DO UPDATE SET "
        "table_name=excluded.table_name, columns=excluded.columns, "
        "row_count=excluded.row_count, created_at=excluded.created_at",
        (dataset_id, name, json.dumps(schema["columns"], ensure_ascii=False),
         len(rows), _now()),
    )
    conn.commit()
    return schema


def schema_for(conn: sqlite3.Connection, dataset_id: str) -> dict[str, Any]:
    if not is_registered(conn, dataset_id):
        return ensure_registered(conn, dataset_id)
    row = conn.execute(
        "SELECT table_name, columns, row_count FROM dataset_tables WHERE dataset_id = ?",
        (dataset_id,),
    ).fetchone()
    return {
        "dataset_id": dataset_id,
        "dataset_name": dataset_repo.get(conn, dataset_id).get("name") or "未命名数据集",
        "table": row["table_name"],
        "columns": json.loads(row["columns"]),
        "row_count": int(row["row_count"]),
    }


def unregister(conn: sqlite3.Connection, dataset_id: str) -> bool:
    row = conn.execute(
        "SELECT table_name FROM dataset_tables WHERE dataset_id = ?", (dataset_id,)
    ).fetchone() if is_registered(conn, dataset_id) else None
    if row:
        conn.execute(f"DROP TABLE IF EXISTS {quote(row['table_name'])}")
    cur = conn.execute("DELETE FROM dataset_tables WHERE dataset_id = ?", (dataset_id,))
    conn.commit()
    return cur.rowcount > 0 or bool(row)


def readonly_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    """从现有连接探测文件路径，另开只读连接执行模型生成的 SQL。"""
    rows = conn.execute("PRAGMA database_list").fetchall()
    path = ""
    for r in rows:
        if r["name"] == "main" and r["file"]:
            path = str(r["file"])
            break
    if not path:
        raise RuntimeError("无法定位 SQLite 主库路径，拒绝在可写连接上执行模型 SQL")
    uri = "file:" + path.replace("\\", "/").replace("?", "%3f") + "?mode=ro"
    ro = sqlite3.connect(uri, uri=True, check_same_thread=False)
    ro.row_factory = sqlite3.Row
    return ro


__all__ = [
    "PREFIX", "table_name", "quote", "is_registered", "registered_tables",
    "ensure_registered", "schema_for", "unregister", "readonly_connection",
]
