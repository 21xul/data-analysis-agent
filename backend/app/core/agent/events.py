"""SSE 事件定义与载荷瘦身。"""
from __future__ import annotations

import time
import uuid
from typing import Any


def event(kind: str, *, step: int = 0, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:8],
        "type": kind,
        "step": step,
        "ts": int(time.time() * 1000),
        "data": data or {},
    }


def slim(result: dict[str, Any], *, max_rows: int = 5, max_points: int = 24) -> dict[str, Any]:
    """发往前端 / 回灌模型的观测副本：截断大表格，避免事件流膨胀。"""
    out = dict(result)
    table = out.get("table")
    if isinstance(table, dict) and isinstance(table.get("rows"), list):
        table = dict(table)
        table["rows"] = table["rows"][:max_rows]
        table["truncated"] = len(result["table"]["rows"]) > max_rows
        out["table"] = table
    for key in ("labels", "values"):
        if isinstance(out.get(key), list) and len(out[key]) > max_points:
            out[key] = out[key][:max_points]
            out["truncated"] = True
    chart = out.get("chart")
    if isinstance(chart, dict):
        chart = dict(chart)
        for key in ("labels", "values"):
            if isinstance(chart.get(key), list):
                chart[key] = chart[key][:max_points]
        out["chart"] = chart
    return out
