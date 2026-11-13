"""元数据仓储：四张结构化表 + 向量点 + 全文取值的读写与三路召回。

对应教程 2.2~2.4：
  - 一行 column_info / metric_info 会拆成 name / description / alias 多个向量点
  - 向量点只存 ref_id，召回后回结构化表取完整 payload（与教程存完整 payload 的取舍相反，
    因为这里三套索引都在同一个 SQLite 文件里，回表零成本且避免元数据更新时的双写不一致）
  - 全文索引只覆盖文本型维度字段的取值
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from app.clients.embedding_client import cosine, embed
from app.entities.metadata import (
    ColumnInfo, MetricInfo, RecallHit, TableInfo,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def tokenize(text: str) -> list[str]:
    """中文分词：优先 jieba 搜索模式，缺失时逐字兜底（FTS5 的 unicode61 不切中文连写）。"""
    s = str(text or "").strip()
    if not s:
        return []
    try:
        import jieba
        return [w for w in jieba.cut_for_search(s) if w.strip()]
    except Exception:  # noqa: BLE001
        return [ch for ch in s if not ch.isspace()]


# ------------------------------------------------------------------ 写入
def upsert_table(conn: sqlite3.Connection, item: TableInfo) -> None:
    conn.execute(
        "INSERT INTO table_info (id,name,role,description,source,created_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role, "
        "description=excluded.description, source=excluded.source",
        (item.id, item.name, item.role, item.description, item.source, _now()),
    )


def upsert_column(conn: sqlite3.Connection, item: ColumnInfo) -> None:
    conn.execute(
        "INSERT INTO column_info "
        "(id,table_id,name,type,role,description,alias,examples,index_value,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "type=excluded.type, role=excluded.role, description=excluded.description, "
        "alias=excluded.alias, examples=excluded.examples, index_value=excluded.index_value",
        (item.id, item.table_id, item.name, item.type, item.role, item.description,
         _dump(item.alias), _dump(item.examples), int(item.index_value), _now()),
    )


def upsert_metric(conn: sqlite3.Connection, item: MetricInfo) -> None:
    conn.execute(
        "INSERT INTO metric_info (id,name,description,relevant_columns,alias,created_at) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "name=excluded.name, description=excluded.description, "
        "relevant_columns=excluded.relevant_columns, alias=excluded.alias",
        (item.id, item.name, item.description, _dump(item.relevant_columns),
         _dump(item.alias), _now()),
    )


def link_metric(conn: sqlite3.Connection, column_id: str, metric_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO column_metric (column_id, metric_id) VALUES (?,?)",
        (column_id, metric_id),
    )


def add_vector_point(
    conn: sqlite3.Connection, ref_type: str, ref_id: str, field: str, text: str
) -> str:
    if not text.strip():
        return ""
    pid = uuid.uuid5(
        uuid.NAMESPACE_URL, f"meta:{ref_type}:{ref_id}:{field}:{text}"
    ).hex
    conn.execute(
        "INSERT INTO meta_vectors (id,ref_type,ref_id,field,text,vector,created_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "text=excluded.text, vector=excluded.vector",
        (pid, ref_type, ref_id, field, text, _dump(embed(text)), _now()),
    )
    return pid


def add_value(
    conn: sqlite3.Connection, value: Any, column_id: str, table_id: str
) -> str:
    text = str(value).strip()
    if not text:
        return ""
    vid = uuid.uuid5(uuid.NAMESPACE_URL, f"value:{column_id}:{text}").hex
    conn.execute(
        "INSERT OR IGNORE INTO value_info (id,value,column_id,table_id,created_at) "
        "VALUES (?,?,?,?,?)", (vid, text, column_id, table_id, _now()),
    )
    conn.execute("DELETE FROM value_fts WHERE value_id = ?", (vid,))
    conn.execute(
        "INSERT INTO value_fts (tokens,value,column_id,value_id) VALUES (?,?,?,?)",
        (" ".join(tokenize(text)), text, column_id, vid),
    )
    return vid


# ------------------------------------------------------------------ 回表
def _column_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "table_id": row["table_id"], "name": row["name"],
        "type": row["type"], "role": row["role"], "description": row["description"],
        "alias": _load(row["alias"], []), "examples": _load(row["examples"], []),
        "index_value": bool(row["index_value"]),
    }


def _table_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "role": row["role"],
            "description": row["description"], "source": row["source"]}


def _metric_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "description": row["description"],
            "relevant_columns": _load(row["relevant_columns"], []),
            "alias": _load(row["alias"], [])}


def get_by_ids(
    conn: sqlite3.Connection, kind: str, ids: Iterable[str]
) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    table, conv = {
        "column": ("column_info", _column_dict),
        "table": ("table_info", _table_dict),
        "metric": ("metric_info", _metric_dict),
    }[kind]
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT * FROM {table} WHERE id IN ({marks})", ids).fetchall()
    by_id = {r["id"]: conv(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def columns_of_tables(
    conn: sqlite3.Connection, table_ids: Iterable[str]
) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(table_ids))
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM column_info WHERE table_id IN ({marks})", ids
    ).fetchall()
    return [_column_dict(r) for r in rows]


# ------------------------------------------------------------------ 三路召回
def vector_search(
    conn: sqlite3.Connection, query: str, ref_type: str, top_k: int
) -> list[RecallHit]:
    qv = embed(query)
    rows = conn.execute(
        "SELECT ref_id, field, text, vector FROM meta_vectors WHERE ref_type = ?",
        (ref_type,),
    ).fetchall()
    best: dict[str, RecallHit] = {}
    for r in rows:
        score = cosine(qv, _load(r["vector"], []))
        if score <= 0:
            continue
        cur = best.get(r["ref_id"])
        if cur is None or score > cur.score:
            best[r["ref_id"]] = RecallHit(
                ref_type=ref_type, ref_id=r["ref_id"], score=round(score, 4),
                source="vector", payload={"field": r["field"], "text": r["text"]},
            )
    return sorted(best.values(), key=lambda h: -h.score)[:top_k]


def fts_search(conn: sqlite3.Connection, query: str, top_k: int) -> list[RecallHit]:
    tokens = tokenize(query)
    if not tokens:
        return []
    match = " OR ".join(f'\"{t}\"' for t in dict.fromkeys(tokens) if t)
    try:
        rows = conn.execute(
            "SELECT value, column_id, value_id, bm25(value_fts) AS rank "
            "FROM value_fts WHERE value_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, top_k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        RecallHit(ref_type="value", ref_id=r["value_id"],
                  score=round(-float(r["rank"]), 4), source="fts",
                  payload={"value": r["value"], "column_id": r["column_id"]})
        for r in rows
    ]


def structured_search(
    conn: sqlite3.Connection, query: str, top_k: int
) -> list[RecallHit]:
    """第三路：别名 / 描述的字面匹配，作为语义向量的确定性兜底。"""
    tokens = [t for t in tokenize(query) if len(t) >= 2][:6]
    if not tokens:
        return []
    out: dict[str, RecallHit] = {}
    for table, kind in (("column_info", "column"), ("metric_info", "metric")):
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        for r in rows:
            text = " ".join(str(r[k] or "") for k in ("name", "description", "alias"))
            score = sum(1 for t in tokens if t in text) / max(len(tokens), 1)
            if score > 0:
                out[r["id"]] = RecallHit(
                    ref_type=kind, ref_id=r["id"], score=round(score, 4),
                    source="structured", payload={"matched": text[:80]},
                )
    return sorted(out.values(), key=lambda h: -h.score)[:top_k]


__all__ = [
    "upsert_table", "upsert_column", "upsert_metric", "link_metric",
    "add_vector_point", "add_value", "get_by_ids", "columns_of_tables",
    "vector_search", "fts_search", "structured_search", "tokenize",
]
