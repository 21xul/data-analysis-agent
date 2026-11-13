"""查询期前半段：关键词抽取 → 三路并行召回 → 合并 → 精筛 → 环境上下文。

对应教程 3.1~3.5。三路分别是：
  column  向量 + 结构化别名（语义召回字段）
  metric  向量 + 结构化别名（语义召回指标）
  value   FTS5 全文（把「华北」「黄金会员」映射到库内真实取值）

多路结果用 RRF 融合；合并阶段按 table_id 归组、把取值挂回字段、补齐主外键，
输出层次化上下文（教程 3.3 的 table_infos / metric_infos YAML 形态）。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Iterable

import yaml

from app.clients import sqlite_client
from app.conf.app_config import app_config
from app.repositories import meta_repo


def extract_keywords(question: str) -> list[str]:
    """jieba TF-IDF 抽关键词；原问题由调用方保留，作为语义兜底（教程 3.1）。"""
    try:
        from jieba import analyse
        tags = analyse.extract_tags(question, topK=app_config.retrieval.keywords_top_k)
        return [str(t) for t in tags if str(t).strip()]
    except Exception:  # noqa: BLE001
        return meta_repo.tokenize(question)[: app_config.retrieval.keywords_top_k]


def rrf(*ranked: Iterable[Any], k: int | None = None) -> list[Any]:
    """Reciprocal Rank Fusion：同一 ref 在多路命中时分数累加，避免量纲不可比。"""
    weight = k or app_config.retrieval.rrf_k
    fused: dict[tuple[str, str], Any] = {}
    scores: dict[tuple[str, str], float] = {}
    for lst in ranked:
        for rank, hit in enumerate(lst, start=1):
            key = (hit.ref_type, hit.ref_id)
            scores[key] = scores.get(key, 0.0) + 1.0 / (weight + rank)
            if key not in fused:
                fused[key] = hit
    out = []
    for key, score in sorted(scores.items(), key=lambda kv: -kv[1]):
        hit = fused[key]
        hit.score = round(score, 6)
        out.append(hit)
    return out


def _queries(question: str, keywords: list[str]) -> list[str]:
    # 原问做语义兜底，关键词做聚焦检索；两者不是二选一
    return [question] + keywords[:3]


def recall_columns(conn: sqlite3.Connection, question: str, keywords: list[str]) -> list[Any]:
    k = app_config.retrieval.top_k_per_route
    lists = []
    for q in _queries(question, keywords):
        lists.append(meta_repo.vector_search(conn, q, "column", k))
        lists.append([h for h in meta_repo.structured_search(conn, q, k)
                      if h.ref_type == "column"])
    return rrf(*lists)[: app_config.retrieval.final_top_k]


def recall_metrics(conn: sqlite3.Connection, question: str, keywords: list[str]) -> list[Any]:
    k = app_config.retrieval.top_k_per_route
    lists = []
    for q in _queries(question, keywords):
        lists.append(meta_repo.vector_search(conn, q, "metric", k))
        lists.append([h for h in meta_repo.structured_search(conn, q, k)
                      if h.ref_type == "metric"])
    return rrf(*lists)[: app_config.retrieval.final_top_k]


def recall_values(conn: sqlite3.Connection, question: str, keywords: list[str]) -> list[Any]:
    k = app_config.retrieval.top_k_per_route
    lists = [meta_repo.fts_search(conn, q, k) for q in _queries(question, keywords)]
    return rrf(*lists)[: app_config.retrieval.final_top_k]


def merge_context(
    conn: sqlite3.Connection,
    column_hits: list[Any], metric_hits: list[Any], value_hits: list[Any],
) -> dict[str, Any]:
    """把散落的召回结果拼成按表分组的层次化上下文。"""
    columns = meta_repo.get_by_ids(conn, "column", [h.ref_id for h in column_hits])
    metrics = meta_repo.get_by_ids(conn, "metric", [h.ref_id for h in metric_hits])

    # 1) 字段按 table_id 归组；2) 取值挂回字段；3) 补齐同表主外键（多表 join 必需）
    table_ids = list(dict.fromkeys([c["table_id"] for c in columns]))
    for v in value_hits:
        cid = v.payload.get("column_id")
        if cid and cid not in [c["id"] for c in columns]:
            extra = meta_repo.get_by_ids(conn, "column", [cid])
            if extra:
                columns.append(extra[0])
                table_ids.append(extra[0]["table_id"])
    table_ids = list(dict.fromkeys(table_ids))
    key_columns = meta_repo.columns_of_tables(conn, table_ids)
    for kc in key_columns:
        if kc["role"] in ("primary_key", "foreign_key") and kc["id"] not in [c["id"] for c in columns]:
            columns.append(kc)

    tables = meta_repo.get_by_ids(conn, "table", table_ids)
    table_infos = [
        {"table": t, "columns": [c for c in columns if c["table_id"] == t["id"]]}
        for t in tables
    ]
    value_infos = [
        {"value": v.payload.get("value"), "column_id": v.payload.get("column_id"),
         "score": v.score}
        for v in value_hits
    ]
    return {
        "table_infos": table_infos,
        "metric_infos": metrics,
        "value_infos": value_infos,
        "columns": columns,
        "recall": {
            "columns": [h.ref_id for h in column_hits],
            "metrics": [h.ref_id for h in metric_hits],
            "values": [v.payload.get("value") for v in value_hits],
        },
    }


def as_yaml(obj: Any) -> str:
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False)


def filter_context(ctx: dict[str, Any], question: str) -> dict[str, Any]:
    """精筛（教程 3.4）。

    mock 模式下不做语义删除（避免误删主外键），只记录待精筛规模；
    接真模型后由 LLM 结合原问题剔除无关表 / 字段 / 指标。
    """
    out = dict(ctx)
    out["filter"] = {
        "strategy": "keep-all-with-keys",
        "question": question,
        "tables_before": len(ctx.get("table_infos", [])),
        "tables_after": len(ctx.get("table_infos", [])),
        "metrics_after": len(ctx.get("metric_infos", [])),
    }
    return out


def enrich(conn: sqlite3.Connection) -> dict[str, str]:
    """教程 3.5：补当前时间、数据库类型与版本，供相对时间与 SQL 方言判断。"""
    return sqlite_client.environment(conn)


def hit_to_dict(hit: Any) -> dict[str, Any]:
    return {"ref_type": hit.ref_type, "ref_id": hit.ref_id,
            "score": hit.score, "source": hit.source, "payload": hit.payload}


__all__ = [
    "extract_keywords", "rrf", "recall_columns", "recall_metrics", "recall_values",
    "merge_context", "as_yaml", "filter_context", "enrich", "hit_to_dict",
]
