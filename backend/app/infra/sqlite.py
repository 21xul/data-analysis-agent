"""SQLite 持久层：原型阶段唯一存储，零外部服务，可直接通过发布预检。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL DEFAULT 'local',
    name        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL DEFAULT 'local',
    dataset_id  TEXT NOT NULL,
    question    TEXT,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL DEFAULT 'local',
    dataset_id  TEXT,
    question    TEXT,
    events      TEXT NOT NULL,
    final       TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    vector      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
-- P1：上传数据集被注册成的只读物理表清单。SQL 白名单只认这里登记过的表名，
-- 绝不接受模型自己拼出来的任意表名。
CREATE TABLE IF NOT EXISTS dataset_tables (
    dataset_id  TEXT PRIMARY KEY,
    table_name  TEXT NOT NULL UNIQUE,
    columns     TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_docs_kind ON documents (kind);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
