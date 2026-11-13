"""指标对比：分组聚合、排名、TOP1 与 CR3 集中度。"""
from __future__ import annotations

import pandas as pd

from app.tools.registry import ToolSpec, object_schema


def run(ctx, args) -> dict:
    df = ctx.frame
    metric = ctx.resolve(args.get("metric"), numeric=True)
    group = ctx.resolve(args.get("group")) or (ctx.category_columns() or [None])[0]
    agg = str(args.get("agg") or "sum")
    if not metric or not group or group not in df.columns:
        return {"tool": "compare", "facts": ["缺少可分组的类目列或数值指标。"], "metrics": [], "table": {"columns": [], "rows": []}}

    series = pd.to_numeric(df[metric], errors="coerce").groupby(df[group].astype(str))
    result = series.sum() if agg == "sum" else series.mean()
    result = result.sort_values(ascending=False)
    total = float(result.sum())
    rows = [
        {"类目": str(k), "数值": round(float(v), 2), "占比": f"{(v / total * 100) if total else 0:.1f}%"}
        for k, v in result.items()
    ]
    cr3 = float(result.head(3).sum()) / total * 100 if total else 0
    facts = []
    if rows:
        facts.append(f"按 {group} 对比 {metric}（{agg}）：{rows[0]['类目']} 最高，为 {rows[0]['数值']}，占 {rows[0]['占比']}；")
        facts.append(f"末位为 {rows[-1]['类目']}（{rows[-1]['数值']}），头部三类目合计 CR3 = {cr3:.1f}%。")
    return {
        "tool": "compare", "metric": metric, "group": group,
        "metrics": [
            {"k": "分组数", "v": f"{len(rows)} 个"},
            {"k": "TOP1", "v": rows[0]["类目"] if rows else "—"},
            {"k": "CR3", "v": f"{cr3:.1f}%"},
            {"k": "极差", "v": str(round(float(result.iloc[0] - result.iloc[-1]), 2)) if len(result) > 1 else "—"},
        ],
        "facts": facts,
        "table": {"columns": ["类目", "数值", "占比"], "rows": rows[:12]},
        "chart": {"type": "bar", "labels": [r["类目"] for r in rows[:12]],
                  "values": [r["数值"] for r in rows[:12]], "title": f"{metric} 按 {group} 对比"},
    }


SPEC = ToolSpec(
    name="compare",
    description="按某个类目字段分组对比数值指标，返回排名、占比、TOP1 与 CR3 集中度。",
    parameters=object_schema({
        "metric": {"type": "string", "description": "数值指标列名"},
        "group": {"type": "string", "description": "分组的类目列名，留空取第一个文本列"},
        "agg": {"type": "string", "enum": ["sum", "mean"], "description": "聚合方式，默认 sum"},
    }),
    handler=run,
)
