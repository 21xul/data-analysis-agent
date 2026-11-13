"""P1 回归：数据集注册表 / 只读 SQL 靶 / 交叉校验 / 逐节点 SSE / HTTP 契约。

运行： python tests/test_p1.py
全程用临时 SQLite，不联网、不需要真实模型、不碰项目主库。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 必须在 import app.main 之前设置，避免 lifespan 连到项目主库
_TMP_HTTP_DB = Path(tempfile.gettempdir()) / "insight_p1_http.db"
os.environ["APP_DB_PATH"] = str(_TMP_HTTP_DB)
# 回归基线必须是确定性 mock，不受本机 .env 中 LLM_MODE=real / 真密钥影响
os.environ["LLM_MODE"] = "mock"

from app.agent.graph import run                                    # noqa: E402
from app.agent.streaming import iter_events                        # noqa: E402
from app.bootstrap import build_registry                           # noqa: E402
from app.clients.sqlite_client import connect, init_db             # noqa: E402
from app.infra import dataset_repo                                 # noqa: E402
from app.services import cross_check as CC                         # noqa: E402
from app.services import dataset_registry as DR                    # noqa: E402
from app.services import sql_service as S                          # noqa: E402
from app.services.meta_knowledge_service import build, sync_dataset  # noqa: E402

PAYLOAD = {
    "name": "P1 回归数据",
    "columns": [
        {"label": "日期", "type": "date"},
        {"label": "渠道", "type": "text"},
        {"label": "销售额", "type": "number"},
    ],
    "rows": [
        {"日期": f"2025-{m:02d}-01", "渠道": ch, "销售额": 100 + m * 10}
        for m in range(1, 7) for ch in ("线上", "线下")
    ],
}
QUESTION = "统计线上渠道的销售总额"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        conn = connect(Path(tmp) / "p1.db")
        init_db(conn)
        build(conn)
        ds = dataset_repo.save(conn, PAYLOAD["name"], PAYLOAD)

        # ------------------------------------------------ 1. 注册表
        schema = DR.ensure_registered(conn, ds)
        check(schema["table"].startswith("ds_"), "表名未派生 ds_ 前缀")
        check(schema["row_count"] == 12, "物理表行数不正确")
        check([c["name"] for c in schema["columns"]] == ["日期", "渠道", "销售额"],
              "中文列名丢失")
        samples = {c["name"]: c["samples"] for c in schema["columns"]}
        check("线上" in samples["渠道"], "文本列样例取值未采集")
        check(any(t.startswith("ds_") for t in S.allowed_tables(conn, ds)),
              "注册后 ds 表未进入白名单")

        count = conn.execute(f"SELECT COUNT(*) AS n FROM {schema['table']}").fetchone()["n"]
        check(count == 12, "物理表数据未写入")
        DR.ensure_registered(conn, ds)  # 幂等重放
        count2 = conn.execute(f"SELECT COUNT(*) AS n FROM {schema['table']}").fetchone()["n"]
        check(count2 == 12, "重复注册不幂等")
        sync_dataset(conn, ds)
        hit = conn.execute(
            "SELECT COUNT(*) AS n FROM value_info WHERE value = '线上'"
        ).fetchone()["n"]
        check(hit >= 1, "上传数据集的取值未进入 FTS 索引")
        print(f"PASS  注册 {schema['table']} · 12 行 · 中文列 · 幂等 · 取值同步")

        # ------------------------------------------------ 2. SQL 护栏 + 只读连接
        sql, source = S.generate(QUESTION, {"value_infos": []}, {}, schema)
        check(source == "mock" and 'SUM("销售额")' in sql, "mock 未生成业务聚合 SQL")
        check("WHERE" in sql, "自然语言取值未映射成 WHERE")
        ok, err = S.validate(conn, sql, ds)
        check(ok, f"合法数据集 SQL 被误拦：{err}")
        for bad in (
            "SELECT * FROM ds_not_registered",
            "DROP TABLE " + schema["table"],
            "SELECT * FROM datasets",
            "SELECT 1; DELETE FROM " + schema["table"],
            "SELECT * FROM " + schema["table"] + " -- x",
        ):
            passed, _ = S.validate(conn, bad, ds)
            check(not passed, f"越权/注入 SQL 未被拦截：{bad}")
        rows = S.execute(conn, sql, dataset_id=ds)
        check(rows and float(rows[0]["结果"]) == 810.0, "只读连接未返回正确数字")

        ro = DR.readonly_connection(conn)
        try:
            try:
                ro.execute("DELETE FROM " + schema["table"])
                raise AssertionError("只读连接竟然允许写入")
            except sqlite3.OperationalError as exc:
                check("readonly" in str(exc).lower(), f"只读报错语义不符：{exc}")
        finally:
            ro.close()
        print("PASS  SQL 白名单 + 注入拦截 + mode=ro 只读连接")

        # ------------------------------------------------ 3. pandas 交叉校验
        cc = CC.check(conn, ds, sql, rows)
        check(cc["covered"] and cc["match"] is True, "标量聚合交叉校验未通过")
        check(cc["sql_value"] == cc["pandas_value"] == 810.0, "交叉校验数值不一致")
        bad_cc = CC.check(conn, ds, sql, [{"结果": 999.0}])
        check(bad_cc["match"] is False, "错误 SQL 结果未被交叉校验发现")
        group_sql = f'SELECT "渠道", SUM("销售额") AS s FROM {schema["table"]} GROUP BY "渠道" LIMIT 10'
        uncovered = CC.check(conn, ds, group_sql, [{"渠道": "线上", "s": 810.0}])
        check(uncovered["covered"] is False, "超出范围的查询不应谎称已校验")
        print("PASS  pandas 交叉校验：一致 / 不一致 / 未覆盖三种状态")

        # ------------------------------------------------ 4. 图与逐节点流
        registry = build_registry(conn)
        final = run(conn, QUESTION, dataset_id=ds, registry=registry, force_branch="sql")
        check(final["dataset_schema"]["table"] == schema["table"], "图未注入执行靶")
        check(final["sql_ok"] and final["cross_check"].get("match") is True,
              "图内交叉校验未生效")
        check(any(e["node"] == "resolve_dataset" for e in final["events"]),
              "缺少 resolve_dataset 节点")
        check(final["recall_evidence"].get("routes"), "召回证据未进 final")

        stream = list(iter_events(conn, QUESTION, dataset_id=ds, registry=registry,
                                  force_branch="sql"))
        kinds = [e["type"] for e in stream]
        check(kinds[0] == "meta" and kinds[-1] == "final", "SSE 事件头尾不正确")
        node_names = [e["data"]["node"] for e in stream if e["type"] == "node"]
        for must in ("extract_keywords", "recall_columns", "recall_values",
                     "resolve_dataset", "generate_sql", "validate_sql",
                     "execute_sql", "finalize"):
            check(must in node_names, f"逐节点流缺少 {must}")
        check(stream[-1]["data"]["cross_check"]["match"] is True, "流末 final 载荷不完整")
        print(f"PASS  LangGraph 17 节点图 · 逐节点 {len(stream)} 事件（含交叉校验）")

        # ------------------------------------------------ 5. 清理注册表
        check(DR.unregister(conn, ds), "注销未生效")
        gone = conn.execute(
            "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name=?",
            (schema["table"],),
        ).fetchone()["n"]
        check(gone == 0, "注销后物理表仍存在")
        conn.close()

    # ---------------------------------------------------- 6. HTTP 契约
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(_TMP_HTTP_DB) + suffix).unlink()
        except OSError:
            pass
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        check(c.get("/api/v1/health").status_code == 200, "health 不可用")
        demo = c.post("/api/v1/datasets/demo", json={}).json()
        check(demo.get("registered") and demo.get("table", "").startswith("ds_"),
              "示例数据未自动注册")
        ds_id = demo["id"]
        sc = c.get(f"/api/v1/datasets/{ds_id}/schema")
        check(sc.status_code == 200 and len(sc.json()["columns"]) == 5, "schema 端点异常")
        check(c.post(f"/api/v1/datasets/{ds_id}/register").json().get("registered"),
              "手动重注册失败")

        # 工作台概览：预览 40 行 + 确定性统计卡
        pv = c.get(f"/api/v1/datasets/{ds_id}/preview?limit=7").json()
        check(pv["total"] == 48 and pv["shown"] == 7 and len(pv["rows"]) == 7,
              "preview limit 契约异常")
        st = c.get(f"/api/v1/datasets/{ds_id}/stats").json()
        check(st["rows"] == 48 and st["columns"] == 5 and st["numeric"] == 3,
              "stats 行数/字段统计不正确")
        check(st["dates"] == 1 and st["missing"] == 0 and st["completeness"] == 100.0,
              "stats 缺失值/完整度口径不正确")
        check(st["size_kb"] > 0 and st["primary_metric"] and st["date_range"],
              "stats 规模/主指标/时间范围缺失")
        check(len(c.get(f"/api/v1/datasets/{ds_id}/preview").json()["rows"]) == 40,
              "preview 默认应为 40 行")

        types, nodes, final_payload = [], [], None
        with c.stream("POST", "/api/v1/graph/runs/stream",
                      json={"question": QUESTION, "dataset_id": ds_id,
                            "force_branch": "sql"}) as resp:
            current = ""
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    current = line[7:]
                    types.append(current)
                elif line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if current == "node":
                        nodes.append(payload["data"]["node"])
                    if current == "final":
                        final_payload = payload["data"]
            check(resp.status_code == 200, "SSE 状态码异常")
        check(types[0] == "meta" and types[-1] == "done", "SSE 缺少 meta/done")
        check("resolve_dataset" in nodes and "execute_sql" in nodes, "SSE 节点轨迹不全")
        check(final_payload and final_payload["cross_check"]["match"] is True,
              "HTTP 链路交叉校验未通过")

        with c.stream("POST", "/api/v1/runs",
                      json={"question": "分析销售额的月度趋势", "dataset_id": ds_id}) as resp:
            old = [l[7:] for l in resp.iter_lines() if l.startswith("event: ")]
        check(resp.status_code == 200 and len(old) >= 10, "旧 ReAct SSE 链路回归")

        paths = c.get("/openapi.json").json()["paths"]
        for p in ("/api/v1/graph/runs/stream", "/api/v1/datasets/{dataset_id}/schema",
                  "/api/v1/datasets/{dataset_id}/register",
                  "/api/v1/datasets/{dataset_id}/stats",
                  "/api/v1/datasets/{dataset_id}/preview"):
            check(p in paths, f"OpenAPI 缺少 {p}")
        print(f"PASS  HTTP：demo 自动注册 / schema / SSE {len(types)} 帧 / 旧链路 / OpenAPI")

    print("\nALL P1 TESTS PASSED")


if __name__ == "__main__":
    main()
