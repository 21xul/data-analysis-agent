"""架构骨架回归（P0）：配置链 / 提示词 / 构建期 / 三路召回 / SQL 闭环 / LangGraph 图。

运行： python tests/test_architecture.py
不依赖真实大模型、不联网、不写项目主库（用临时 SQLite）。
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.graph import build_graph, run
from app.clients.sqlite_client import connect, init_db
from app.conf.app_config import ROOT, app_config, effective_mode
from app.models import meta_schema
from app.prompt.loader import available, load
from app.services import retrieval_service as R
from app.services import sql_service as S
from app.services.meta_knowledge_service import build

_QUESTION = "统计华北地区的销售总额"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_config_chain() -> None:
    check(app_config.project.name == "insight-agent-v2", "配置对象未加载")
    check(app_config.llm.model == "qwen3.8-max", "模型名应来自 YAML")
    check(app_config.db.dialect == "sqlite", "C 路线应为 SQLite")
    check(app_config.retrieval.rrf_k == 60, "RRF 参数应来自 YAML")
    check(effective_mode() in ("mock", "real"), "模式解析失败")
    print("PASS  配置链 dataclass + OmegaConf + .env 覆盖")


def test_prompts() -> None:
    names = available()
    for n in ("react_system.md", "sql_generate.md", "sql_correct.md", "conclusion.md"):
        check(n in names, f"缺少提示词 {n}")
    text = load("sql_generate", dialect="sqlite", db_version="3.53", now="2026-11-10",
                question=_QUESTION, table_infos="-", metric_infos="-", value_infos="-",
                dataset_schema="（本次未指定数据集）", max_rows=500)
    check("{{" not in text, "提示词变量未替换")
    print("PASS  静态提示词外置与变量替换")


def test_secret_hygiene() -> None:
    pattern = re.compile(r"sk-[A-Za-z0-9._-]{12,}")
    exts = {".py", ".yaml", ".yml", ".md", ".txt", ".example", ".json", ".js", ".vue"}
    hits: list[str] = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts or p.suffix not in exts:
            continue
        if ".env" in p.name and p.name != ".env.example":
            continue
        try:
            if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p))
        except OSError:
            continue
    check(not hits, f"发现疑似密钥字面量：{hits}")
    print("PASS  全项目无密钥字面量落盘")


def main() -> None:
    test_config_chain()
    test_prompts()
    test_secret_hygiene()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        conn = connect(Path(tmp) / "arch.db")
        init_db(conn)
        stats = build(conn)
        check(stats["table_info"] >= 5, "内置星型模型表未写入")
        check(stats["meta_vectors"] >= 60, "name/description/alias 多点向量未建立")
        check(stats["value_info"] >= 20, "字段取值索引未建立")
        check(stats["value_fts"] == stats["value_info"], "FTS 与结构化取值数不一致")
        print(f"PASS  构建期主线 {stats['table_info']} 表 / {stats['column_info']} 字段 / "
              f"{stats['meta_vectors']} 向量点 / {stats['value_fts']} 取值")

        kw = R.extract_keywords(_QUESTION)
        cols = R.recall_columns(conn, _QUESTION, kw)
        mets = R.recall_metrics(conn, _QUESTION, kw)
        vals = R.recall_values(conn, _QUESTION, kw)
        check(any("region_name" in h.ref_id for h in cols), "字段路未召回 region_name")
        check(any("order_amount" in h.ref_id for h in cols), "字段路未召回 order_amount")
        check(any(h.ref_id == "GMV" for h in mets), "指标路未召回 GMV")
        check(any(h.payload.get("value") == "华北" for h in vals), "取值路未命中「华北」")
        ctx = R.merge_context(conn, cols, mets, vals)
        check(len(ctx["table_infos"]) >= 2, "未按 table_id 归组")
        check(any(c["role"] in ("primary_key", "foreign_key") for c in ctx["columns"]),
              "未补齐主外键字段")
        check("db_version" in R.enrich(conn), "环境上下文缺失数据库版本")
        print(f"PASS  三路召回 字段={len(cols)} 指标={len(mets)} 取值={len(vals)} "
              f"· 归组表={len(ctx['table_infos'])}")

        ok, _ = S.validate(conn, "SELECT role, COUNT(*) AS cnt FROM table_info GROUP BY role LIMIT 50")
        check(ok, "合法只读 SQL 应通过")
        for bad in ("DROP TABLE table_info", "SELECT * FROM datasets",
                    "SELECT 1; DROP TABLE table_info", "SELECT * FROM table_info -- x"):
            passed, _ = S.validate(conn, bad)
            check(not passed, f"注入/越权 SQL 未被拦截：{bad}")
        fixed = S.correct("SELECT * FROM datasets;", "表不在只读白名单", _QUESTION, ctx, 1)
        check(S.validate(conn, fixed)[0], "纠错后的 SQL 仍不可用")
        rows = S.execute(conn, "SELECT role, COUNT(*) AS cnt FROM table_info GROUP BY role LIMIT 50")
        check(len(rows) > 0, "只读执行无结果")
        print("PASS  SQL 闭环：白名单 + EXPLAIN + 纠错 + 只读执行")

        graph = build_graph(conn)
        check("recall_columns" in graph.nodes and "validate_sql" in graph.nodes,
              "节点缺失")
        f_sql = run(conn, _QUESTION, force_branch="sql")
        check(f_sql["branch"] == "sql", "SQL 分支路由失败")
        check(f_sql["sql_ok"] and f_sql["sql_rows"], "SQL 分支未产出结果")
        check(any(e["node"] == "finalize" for e in f_sql["events"]), "轨迹未闭合")
        f_react = run(conn, "分析销售额的月度趋势", force_branch="react")
        check(f_react["branch"] == "react", "ReAct 分支路由失败")
        check(any(e["node"] == "react_analyze" for e in f_react["events"]), "ReAct 节点缺失")
        print(f"PASS  LangGraph 双分支图 {len(graph.nodes)} 节点 · "
              f"sql 轨迹 {len(f_sql['events'])} 事件 / react 轨迹 {len(f_react['events'])} 事件")

        stats2 = build(conn)
        check(stats2["meta_vectors"] == stats["meta_vectors"], "重复构建不幂等")
        print("PASS  构建脚本可重复执行（幂等）")
        conn.close()

    print("\nALL ARCHITECTURE TESTS PASSED")


if __name__ == "__main__":
    main()
