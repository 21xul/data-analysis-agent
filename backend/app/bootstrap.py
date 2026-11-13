"""依赖组装：工具注册表、数据集上下文。唯一做 wiring 的地方。"""
from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from app.core.config import settings
from app.infra import dataset_repo
from app.rag.retriever import search
from app.tools import anomaly, chart, compare, profile, query, trend
from app.tools.registry import ToolContext, ToolRegistry, ToolSpec

log = logging.getLogger("insight.bootstrap")


def _rag_handler(conn):
    def handler(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
        q = str(args.get("query") or ctx.extras.get("question") or "指标口径")
        hits = search(conn, q, top_k=3)
        return {
            "tool": "rag_search",
            "facts": [f"{h['title']}：{h['content']}" for h in hits],
            "metrics": [{"k": "命中文档", "v": f"{len(hits)} 篇"}],
            "documents": [{"id": h["id"], "title": h["title"], "score": h["score"]} for h in hits],
        }
    return handler


def build_registry(conn) -> ToolRegistry:
    registry = ToolRegistry()
    for spec in (profile.SPEC, trend.SPEC, anomaly.SPEC, compare.SPEC, query.SPEC, chart.SPEC):
        registry.register(spec)
    registry.register(ToolSpec(
        name="rag_search",
        description="检索业务指标口径、字段语义与分析规范，用于确认指标定义或字段映射。",
        parameters={"type": "object", "properties": {
            "query": {"type": "string", "description": "要检索的口径或字段名"}
        }},
        handler=_rag_handler(conn),
    ))
    from app.skills.registry import register_all
    skills = register_all(registry)
    log.info("skills loaded: %s", skills)

    if settings.mcp_enabled:
        try:
            from app.mcp.client import StdioMCPClient
            from app.mcp.registry import register_mcp_tools
            loaded = register_mcp_tools(registry, StdioMCPClient())
            log.info("mcp tools loaded: %s", loaded)
        except Exception as exc:  # noqa: BLE001 - MCP 失败不影响主链路
            log.warning("MCP 未启用：%s", type(exc).__name__)
    return registry


def build_context(conn, dataset_id: str) -> ToolContext:
    ds = dataset_repo.get(conn, dataset_id)
    rows = ds.get("rows") or []
    df = pd.DataFrame(rows)
    for col in ds.get("columns") or []:
        label = col["label"]
        if label not in df.columns:
            continue
        if col.get("type") == "number":
            df[label] = pd.to_numeric(df[label], errors="coerce")
        elif col.get("type") == "date":
            df[label] = pd.to_datetime(df[label], errors="coerce")
    return ToolContext(
        frame=df,
        dataset_name=ds.get("name") or "未命名数据集",
        columns=ds.get("columns") or [],
        conn=conn,
        extras={"dataset_id": dataset_id},
    )


def infer_columns(df: pd.DataFrame) -> list[dict[str, str]]:
    out = []
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            kind = "number"
        else:
            parsed = pd.to_datetime(s, errors="coerce", format="mixed")
            kind = "date" if len(s) and parsed.notna().mean() >= 0.8 else "text"
        out.append({"key": str(col), "label": str(col), "type": kind})
    return out


def dataframe_to_payload(df: pd.DataFrame, name: str) -> dict[str, Any]:
    """用 to_json 统一处理 NaN / Timestamp，保证载荷可直接 JSON 序列化。"""
    rows = json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso"))
    return {"name": name, "columns": infer_columns(df), "rows": rows}
