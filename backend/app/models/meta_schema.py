"""持久化形状：单文件 SQLite 内的结构化元数据 + 语义向量 + 全文取值索引。

C 路线对教程第 2 章三套基础服务的等价替换（零外部服务、可过发布预检）：

    MySQL(meta)  → table_info / column_info / metric_info / column_metric
    Qdrant       → meta_vectors（name / description / alias 分别建点，payload 回表取）
    Elasticsearch→ value_info + value_fts(FTS5，jieba 分词后写入 tokens)
    TEI          → app/clients/embedding_client.py（本地确定性 embedding，可插拔）
"""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS table_info (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'builtin',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS column_info (
    id          TEXT PRIMARY KEY,
    table_id    TEXT NOT NULL,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'text',
    role        TEXT NOT NULL DEFAULT 'dimension',
    description TEXT NOT NULL DEFAULT '',
    alias       TEXT NOT NULL DEFAULT '[]',
    examples    TEXT NOT NULL DEFAULT '[]',
    index_value INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_column_table ON column_info(table_id);
CREATE TABLE IF NOT EXISTS metric_info (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    relevant_columns  TEXT NOT NULL DEFAULT '[]',
    alias             TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS column_metric (
    column_id TEXT NOT NULL,
    metric_id TEXT NOT NULL,
    PRIMARY KEY (column_id, metric_id)
);
CREATE TABLE IF NOT EXISTS value_info (
    id         TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    column_id  TEXT NOT NULL,
    table_id   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_value_column ON value_info(column_id);
CREATE VIRTUAL TABLE IF NOT EXISTS value_fts USING fts5(
    tokens,
    value UNINDEXED,
    column_id UNINDEXED,
    value_id UNINDEXED,
    tokenize = 'unicode61'
);
CREATE TABLE IF NOT EXISTS meta_vectors (
    id         TEXT PRIMARY KEY,
    ref_type   TEXT NOT NULL,
    ref_id     TEXT NOT NULL,
    field      TEXT NOT NULL,
    text       TEXT NOT NULL,
    vector     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meta_vec_ref ON meta_vectors(ref_type, ref_id);
"""

META_TABLES = (
    "table_info", "column_info", "metric_info", "column_metric",
    "value_info", "meta_vectors", "value_fts",
)


def install(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def purge(conn: sqlite3.Connection) -> None:
    """清空可重建的知识库内容（不碰 datasets / analyses / runs 业务表）。"""
    for table in META_TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in META_TABLES:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        out[table] = int(row["n"])
    return out


__all__ = ["SCHEMA", "META_TABLES", "install", "purge", "counts"]
