"""数据画像：规模、字段类型、缺失、重复与数值分布。"""
from __future__ import annotations

import pandas as pd

from app.tools.registry import ToolSpec, object_schema


def run(ctx, args) -> dict:
    df = ctx.frame
    numeric = [ctx.resolve(c["label"], numeric=True) for c in ctx.columns if c.get("type") == "number"]
    numeric = [c for c in numeric if c and c in df.columns]
    stats = []
    for col in numeric[:8]:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if s.empty:
            continue
        stats.append({
            "字段": col,
            "均值": round(float(s.mean()), 2),
            "中位数": round(float(s.median()), 2),
            "最小值": round(float(s.min()), 2),
            "最大值": round(float(s.max()), 2),
            "标准差": round(float(s.std(ddof=0)), 2),
            "缺失": int(df[col].isna().sum()),
        })
    missing = int(df.isna().sum().sum())
    dup = int(df.duplicated().sum())
    return {
        "tool": "profile",
        "metrics": [
            {"k": "行数", "v": f"{len(df)} 行"},
            {"k": "列数", "v": f"{len(df.columns)} 列"},
            {"k": "缺失单元格", "v": str(missing)},
            {"k": "重复行", "v": str(dup)},
        ],
        "facts": [f"数据集共 {len(df)} 行、{len(df.columns)} 列，缺失单元格 {missing} 个，重复行 {dup} 行。"],
        "columns": [{"label": c["label"], "type": c.get("type")} for c in ctx.columns],
        "stats": stats,
        "table": {"columns": ["字段", "均值", "中位数", "最小值", "最大值", "标准差", "缺失"], "rows": stats},
    }


SPEC = ToolSpec(
    name="profile",
    description="查看数据集的整体画像：行列数、字段类型、缺失与重复、各数值字段的分布统计。分析前建议先调用。",
    parameters=object_schema({}),
    handler=run,
)
