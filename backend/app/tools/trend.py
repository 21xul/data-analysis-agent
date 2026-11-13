"""趋势分析：按时间周期聚合、环比、线性斜率与拟合优度。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.tools.registry import ToolSpec, object_schema


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def run(ctx, args) -> dict:
    df = ctx.frame.copy()
    metric = ctx.resolve(args.get("metric"), numeric=True)
    date_col = ctx.resolve(args.get("date")) or ctx.date_column()
    if not metric:
        return {"tool": "trend", "facts": ["数据集中没有可分析的数值字段。"], "metrics": [], "series": []}

    labels: list[str] = []
    values: list[float] = []
    if date_col and date_col in df.columns:
        dt = pd.to_datetime(df[date_col], errors="coerce")
        freq = str(args.get("freq") or "M").upper()
        period = dt.dt.to_period("M" if freq.startswith("M") else "Q" if freq.startswith("Q") else "Y")
        grouped = pd.to_numeric(df[metric], errors="coerce").groupby(period).sum().sort_index()
        labels = [str(p) for p in grouped.index]
        values = [round(float(v), 2) for v in grouped.values]
    else:
        s = pd.to_numeric(df[metric], errors="coerce").dropna()
        labels = [str(i + 1) for i in range(len(s))]
        values = [round(float(v), 2) for v in s.values]

    facts: list[str] = []
    metrics: list[dict] = []
    if len(values) >= 2:
        first, last = values[0], values[-1]
        growth = (last - first) / abs(first) if first else 0.0
        mom = [((values[i] - values[i - 1]) / abs(values[i - 1]))
               if values[i - 1] else 0.0 for i in range(1, len(values))]
        x = np.arange(len(values), dtype=float)
        slope, intercept = np.polyfit(x, np.asarray(values, dtype=float), 1)
        pred = slope * x + intercept
        ss_res = float(((np.asarray(values) - pred) ** 2).sum())
        ss_tot = float(((np.asarray(values) - np.mean(values)) ** 2).sum())
        r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
        metrics = [
            {"k": "首期", "v": str(round(first, 2))},
            {"k": "末期", "v": str(round(last, 2))},
            {"k": "累计变化", "v": _pct(growth)},
            {"k": "平均环比", "v": _pct(float(np.mean(mom))) if mom else "—"},
            {"k": "线性斜率", "v": str(round(float(slope), 2))},
            {"k": "R²", "v": str(round(float(r2), 3))},
        ]
        direction = "上升" if slope > 0 else "下降" if slope < 0 else "基本持平"
        facts.append(
            f"{metric} 按{'时间' if date_col else '记录顺序'}共 {len(values)} 期，"
            f"首期 {round(first, 2)} → 末期 {round(last, 2)}，累计变化 {_pct(growth)}；"
            f"线性拟合呈{direction}趋势（斜率 {round(float(slope), 2)}，R² {round(float(r2), 3)}）。"
        )
        peak_i = int(np.argmax(values))
        facts.append(f"峰值出现在第 {peak_i + 1} 期（{labels[peak_i]}），数值 {values[peak_i]}。")
    return {
        "tool": "trend", "metric": metric, "date_col": date_col,
        "labels": labels, "values": values,
        "metrics": metrics, "facts": facts,
        "chart": {"type": "line", "labels": labels, "values": values, "title": f"{metric} 趋势"},
    }


SPEC = ToolSpec(
    name="trend",
    description="分析某个数值指标随时间的变化趋势，返回各期数值、环比、线性回归斜率与 R²。",
    parameters=object_schema({
        "metric": {"type": "string", "description": "数值指标列名，留空取第一个数值列"},
        "date": {"type": "string", "description": "日期列名，留空自动推断"},
        "freq": {"type": "string", "enum": ["M", "Q", "Y"], "description": "聚合粒度，默认按月 M"},
    }),
    handler=run,
)
