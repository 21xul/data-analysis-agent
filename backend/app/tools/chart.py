"""图表规格生成：数字仍由 pandas 重算，模型只选择图形类型与维度。"""
from __future__ import annotations

from app.tools import compare, trend
from app.tools.registry import ToolSpec, object_schema


def run(ctx, args) -> dict:
    kind = str(args.get("kind") or "line")
    result = trend.run(ctx, args) if kind == "line" else compare.run(ctx, args)
    chart = result.get("chart") or {"type": kind, "labels": [], "values": [], "title": "无可用数据"}
    return {
        "tool": "chart",
        "metrics": result.get("metrics", []),
        "facts": [f"已生成{('折线' if kind == 'line' else '柱状')}图：{chart.get('title', '')}。"],
        "chart": chart,
    }


SPEC = ToolSpec(
    name="chart",
    description="生成可视化图表规格（折线/柱状）。数字由后端重新聚合计算。",
    parameters=object_schema({
        "kind": {"type": "string", "enum": ["line", "bar"], "description": "图形类型"},
        "metric": {"type": "string", "description": "数值指标列名"},
        "date": {"type": "string", "description": "折线图的时间列"},
        "group": {"type": "string", "description": "柱状图的分组列"},
    }),
    handler=run,
)
