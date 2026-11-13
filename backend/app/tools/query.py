"""条件查询：筛选、排序、取前 N 行，返回明细表。"""
from __future__ import annotations

import json

import pandas as pd

from app.tools.registry import ToolSpec, object_schema

_OPS = {
    "gt": lambda s, v: s > v,
    "gte": lambda s, v: s >= v,
    "lt": lambda s, v: s < v,
    "lte": lambda s, v: s <= v,
    "eq": lambda s, v: s == v,
    "contains": lambda s, v: s.astype(str).str.contains(str(v), case=False, na=False),
}


def run(ctx, args) -> dict:
    df = ctx.frame.copy()
    applied: list[str] = []
    for f in (args.get("filters") or [])[:5]:
        col = ctx.resolve(f.get("column"))
        op = str(f.get("op") or "eq")
        if not col or col not in df.columns or op not in _OPS:
            continue
        value = f.get("value")
        series = df[col]
        if op in ("gt", "gte", "lt", "lte"):
            series = pd.to_numeric(series, errors="coerce")
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
        try:
            df = df[_OPS[op](series, value)]
        except Exception:  # noqa: BLE001 - 单个条件失败不影响其余条件
            continue
        applied.append(f"{col} {op} {value}")

    sort_by = ctx.resolve(args.get("sort_by"))
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=str(args.get("order") or "desc").lower() != "desc")
    limit = max(1, min(int(args.get("limit") or 10), 50))
    head = df.head(limit)
    # 用 to_json 统一处理 NaN / Timestamp / numpy 标量，保证 SSE 可直接序列化
    rows = json.loads(head.to_json(orient="records", force_ascii=False, date_format="iso"))
    ratio = len(df) / len(ctx.frame) * 100 if len(ctx.frame) else 0
    return {
        "tool": "query",
        "metrics": [
            {"k": "命中行数", "v": f"{len(df)} 行"},
            {"k": "占全量", "v": f"{ratio:.1f}%"},
            {"k": "筛选条件", "v": f"{len(applied)} 个"},
            {"k": "展示", "v": f"前 {len(rows)} 行"},
        ],
        "facts": [("按 " + "、".join(applied) + " 筛选，" if applied else "未附加筛选条件，")
                  + f"命中 {len(df)} 行，占全量 {ratio:.1f}%。"],
        "table": {"columns": list(head.columns), "rows": rows},
    }


SPEC = ToolSpec(
    name="query",
    description="按条件筛选数据行并排序，返回明细。支持 gt/gte/lt/lte/eq/contains。",
    parameters=object_schema({
        "filters": {"type": "array", "items": {"type": "object", "properties": {
            "column": {"type": "string"}, "op": {"type": "string"}, "value": {}}},
            "description": "筛选条件数组"},
        "sort_by": {"type": "string"},
        "order": {"type": "string", "enum": ["asc", "desc"]},
        "limit": {"type": "integer"},
    }),
    handler=run,
)
