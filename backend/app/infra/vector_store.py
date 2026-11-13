"""向量存储薄封装：向量以 JSON 存 SQLite，余弦相似度在 Python 内计算。

原型不引入 FAISS / pgvector / 外部向量库；切换到托管向量库时只需替换本文件。
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert(
    conn: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    content: str,
    vector: list[float],
    doc_id: str | None = None,
) -> str:
    did = doc_id or uuid.uuid5(uuid.NAMESPACE_URL, f"insight:{kind}:{title}").hex
    conn.execute(
        "INSERT INTO documents (id, kind, title, content, vector, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET content=excluded.content, vector=excluded.vector",
        (did, kind, title, content, json.dumps(vector), _now()),
    )
    conn.commit()
    return did


def count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"])


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def search(
    conn: sqlite3.Connection,
    query_vector: list[float],
    *,
    top_k: int = 3,
    kinds: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT id, kind, title, content, vector FROM documents"
    params: tuple[Any, ...] = ()
    if kinds:
        sql += " WHERE kind IN (" + ",".join("?" for _ in kinds) + ")"
        params = kinds
    rows = conn.execute(sql, params).fetchall()
    scored = [
        {
            "id": r["id"],
            "kind": r["kind"],
            "title": r["title"],
            "content": r["content"],
            "score": cosine(query_vector, json.loads(r["vector"])),
        }
        for r in rows
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return [s for s in scored[:top_k] if s["score"] > 0]
