"""SQLite 客户端：连接生命周期与「环境上下文」探测。

业务层只从这里拿连接与元信息；驱动细节留在 app/infra/sqlite.py（兼容层）。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.conf.app_config import app_config
from app.infra.sqlite import connect, init_db  # noqa: F401 - 再导出，保持单一实现

__all__ = ["connect", "init_db", "db_version", "table_names", "environment"]


def db_version(conn: sqlite3.Connection) -> str:
    return sqlite3.sqlite_version


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def environment(conn: sqlite3.Connection) -> dict[str, str]:
    """教程 3.5「增加额外上下文」：时间 + 数据库类型 / 版本 / 方言。"""
    try:
        now = datetime.now(ZoneInfo(app_config.project.timezone))
    except Exception:  # noqa: BLE001 - Windows 无 tzdata 时退回本地时区
        now = datetime.now().astimezone()
    return {
        "now": now.strftime("%Y-%m-%d %H:%M:%S %z"),
        "timezone": app_config.project.timezone,
        "dialect": app_config.db.dialect,
        "db_version": db_version(conn),
        "max_rows": str(app_config.agent.max_rows),
    }
