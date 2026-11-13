"""构建期主线：配置驱动地把元数据同步进知识库（教程 2.5）。

流程：读 conf/meta_knowledge.yaml → 写四张结构化表 → 字段/指标按
name / description / alias **分别**向量化 → 文本型维度字段取值写入 FTS5 →
扫描 datasets 表把「上传型数据集」动态纳入（v2 相对教程的扩展）。

可重复执行：每次先 purge 可重建部分，再全量构建，不触碰业务数据表。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from app.conf.app_config import ROOT, app_config
from app.entities.metadata import ColumnInfo, MetricInfo, TableInfo
from app.models import meta_schema
from app.repositories import meta_repo


def config_path() -> Path:
    p = Path(app_config.meta_knowledge.config_path)
    return p if p.is_absolute() else (ROOT / p).resolve()


def read_config(path: Path | None = None) -> dict[str, Any]:
    p = path or config_path()
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _vectorize_column(conn: sqlite3.Connection, item: ColumnInfo) -> int:
    n = 0
    meta_repo.add_vector_point(conn, "column", item.id, "name", item.name)
    n += 1
    if item.description.strip():
        meta_repo.add_vector_point(conn, "column", item.id, "description", item.description)
        n += 1
    for i, alias in enumerate(item.alias):
        meta_repo.add_vector_point(conn, "column", item.id, f"alias[{i}]", alias)
        n += 1
    return n


def _vectorize_metric(conn: sqlite3.Connection, item: MetricInfo) -> int:
    n = 0
    meta_repo.add_vector_point(conn, "metric", item.id, "name", item.name)
    n += 1
    if item.description.strip():
        meta_repo.add_vector_point(conn, "metric", item.id, "description", item.description)
        n += 1
    for i, alias in enumerate(item.alias):
        meta_repo.add_vector_point(conn, "metric", item.id, f"alias[{i}]", alias)
        n += 1
    return n


def sync_dataset(
    conn: sqlite3.Connection,
    dataset_id: str,
    payload: dict[str, Any] | None = None,
    name: str | None = None,
) -> bool:
    """增量同步单个上传数据集的元数据（P1：上传后无需重启即可被三路召回命中）。

    只索引字段语义与文本型维度取值，不把数据行写进向量库——保持「RAG 只索引口径」。
    """
    if payload is None:
        row = conn.execute(
            "SELECT name, payload FROM datasets WHERE id = ?", (dataset_id,)
        ).fetchone()
        if not row:
            return False
        name = name or row["name"]
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            return False
    table_id = f"dataset:{dataset_id}"
    display = payload.get("name") or name or "未命名数据集"
    meta_repo.upsert_table(conn, TableInfo(
        id=table_id, name=display, role="dataset",
        description=f"用户上传的数据集：{display}。字段由上传时推断。",
        source="uploaded",
    ))
    data_rows = payload.get("rows") or []
    for col in payload.get("columns") or []:
        label = str(col.get("label") or col.get("key") or "").strip()
        if not label:
            continue
        ctype = str(col.get("type") or "text")
        column_id = f"{table_id}.{label}"
        seen: list[str] = []
        if ctype == "text":
            for row in data_rows:
                v = row.get(label)
                if v is None:
                    continue
                s = str(v)
                if s not in seen:
                    seen.append(s)
                if len(seen) >= 50:
                    break
        item = ColumnInfo(
            id=column_id, table_id=table_id, name=label, type=ctype,
            role="measure" if ctype == "number" else "dimension",
            description=f"{display} 的字段「{label}」",
            alias=[label], examples=seen[:10], index_value=(ctype == "text"),
        )
        meta_repo.upsert_column(conn, item)
        _vectorize_column(conn, item)
        for value in seen[:50]:
            meta_repo.add_value(conn, value, column_id, table_id)
    conn.commit()
    return True


def _sync_uploaded_datasets(conn: sqlite3.Connection) -> int:
    """全量构建时扫描 datasets 表并逐个增量同步。"""
    try:
        rows = conn.execute("SELECT id, name, payload FROM datasets").fetchall()
    except sqlite3.OperationalError:
        return 0
    for r in rows:
        try:
            payload = json.loads(r["payload"])
        except (TypeError, ValueError):
            continue
        sync_dataset(conn, r["id"], payload, name=r["name"])
    return len(rows)


def build(conn: sqlite3.Connection, path: Path | None = None) -> dict[str, Any]:
    """执行一次完整构建；返回各索引的条目数，便于回归断言。"""
    cfg = read_config(path)
    meta_schema.install(conn)
    meta_schema.purge(conn)

    for t in cfg.get("tables") or []:
        meta_repo.upsert_table(conn, TableInfo(
            id=t["id"], name=t.get("name", t["id"]), role=t.get("role", "dim"),
            description=t.get("description", ""), source=t.get("source", "builtin"),
        ))

    for c in cfg.get("columns") or []:
        item = ColumnInfo(
            id=c["id"], table_id=c["table_id"], name=c["name"],
            type=c.get("type") or "text", role=c.get("role", "dimension"),
            description=c.get("description", ""), alias=list(c.get("alias") or []),
            examples=list(c.get("examples") or []), index_value=bool(c.get("index_value")),
        )
        meta_repo.upsert_column(conn, item)
        _vectorize_column(conn, item)
        if item.index_value:
            for value in item.examples:
                meta_repo.add_value(conn, value, item.id, item.table_id)

    for m in cfg.get("metrics") or []:
        item = MetricInfo(
            id=m["id"], name=m.get("name", m["id"]),
            description=m.get("description", ""),
            relevant_columns=list(m.get("relevant_columns") or []),
            alias=list(m.get("alias") or []),
        )
        meta_repo.upsert_metric(conn, item)
        _vectorize_metric(conn, item)
        for column_id in item.relevant_columns:
            meta_repo.link_metric(conn, column_id, item.id)

    datasets = _sync_uploaded_datasets(conn) if cfg.get("dynamic_datasets") else 0
    conn.commit()
    return {
        "config": str((path or config_path()).relative_to(ROOT)) if (path or config_path()).is_relative_to(ROOT) else str(path or config_path()),
        "datasets_synced": datasets,
        **meta_schema.counts(conn),
    }


__all__ = ["build", "read_config", "config_path"]
