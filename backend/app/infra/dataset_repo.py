"""数据集仓库：CSV 解析结果以 JSON 载荷落 SQLite。"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.errors import DatasetNotFound


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(conn: sqlite3.Connection, name: str, dataset: dict[str, Any]) -> str:
    ds_id = dataset.get("id") or uuid.uuid4().hex
    dataset = dict(dataset, id=ds_id)
    conn.execute(
        "INSERT INTO datasets (id, name, payload, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, payload=excluded.payload",
        (ds_id, name, json.dumps(dataset, ensure_ascii=False), _now()),
    )
    conn.commit()
    return ds_id


def get(conn: sqlite3.Connection, ds_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT payload FROM datasets WHERE id = ?", (ds_id,)).fetchone()
    if not row:
        raise DatasetNotFound(f"数据集 {ds_id} 不存在")
    return json.loads(row["payload"])


def list_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, created_at FROM datasets ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    return [dict(r) for r in rows]


def remove(conn: sqlite3.Connection, ds_id: str) -> bool:
    cur = conn.execute("DELETE FROM datasets WHERE id = ?", (ds_id,))
    conn.commit()
    return cur.rowcount > 0


def save_run(
    conn: sqlite3.Connection,
    dataset_id: str | None,
    question: str,
    events: list[dict[str, Any]],
    final: str | None,
) -> str:
    run_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO runs (id, dataset_id, question, events, final, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, dataset_id, question, json.dumps(events, ensure_ascii=False), final, _now()),
    )
    conn.commit()
    return run_id
