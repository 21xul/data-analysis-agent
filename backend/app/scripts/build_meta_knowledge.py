"""离线构建元数据知识库（构建期主线入口）。

    cd backend
    python -m app.scripts.build_meta_knowledge
    python -m app.scripts.build_meta_knowledge --db data/agent.db --config conf/meta_knowledge.yaml

配置驱动、可重复执行：每次先清空可重建的索引，再全量构建。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.clients.sqlite_client import connect, init_db
from app.conf.app_config import ROOT, resolve_data_dir
from app.services.meta_knowledge_service import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建元数据知识库")
    parser.add_argument("--db", default="", help="SQLite 路径（默认 conf/app_config.yaml 的 db.path）")
    parser.add_argument("--config", default="", help="元数据配置 YAML 路径")
    args = parser.parse_args(argv)

    db = Path(args.db) if args.db else (resolve_data_dir() / Path("agent.db"))
    if not db.is_absolute():
        db = (ROOT / db).resolve()
    cfg = Path(args.config) if args.config else None
    if cfg and not cfg.is_absolute():
        cfg = (ROOT / cfg).resolve()

    conn = connect(db)
    init_db(conn)              # 业务表（datasets / analyses / runs / documents）
    stats = build(conn, cfg)   # 元数据表 / 向量 / FTS
    conn.close()
    print(json.dumps({"db": str(db), **stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
