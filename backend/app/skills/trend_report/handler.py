"""组合多个确定性工具，产出一份结构化趋势报告。"""
from __future__ import annotations

from app.tools import compare, profile, trend


def run(ctx, args) -> dict:
    metric = args.get("metric")
    p = profile.run(ctx, {})
    t = trend.run(ctx, {"metric": metric})
    c = compare.run(ctx, {"metric": metric})
    facts = p.get("facts", []) + t.get("facts", []) + c.get("facts", [])
    return {
        "tool": "skill__trend_report",
        "skill": "trend_report",
        "metrics": (t.get("metrics") or [])[:3] + (c.get("metrics") or [])[:2],
        "facts": facts[:6],
        "chart": t.get("chart"),
        "table": c.get("table"),
    }
