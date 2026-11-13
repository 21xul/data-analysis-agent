"""异常识别：IQR 围栏 + Z-score 双重规则，定位到具体记录。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.tools.registry import ToolSpec, object_schema


def run(ctx, args) -> dict:
    df = ctx.frame
    requested = args.get("metric")
    metric = ctx.resolve(requested, numeric=True) if requested else None
    z_limit = float(args.get("z_threshold") or 2.5)
    iqr_k = float(args.get("iqr_k") or 3.0)
    # 未指定字段时检查全部数值列
    targets = [metric] if metric else ctx.number_columns()
    found: list[dict] = []

    for col in targets[:6]:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        valid = s.dropna()
        if len(valid) < 4:
            continue
        mean, std = float(valid.mean()), float(valid.std(ddof=0))
        q1, q3 = float(valid.quantile(0.25)), float(valid.quantile(0.75))
        lo, hi = q1 - iqr_k * (q3 - q1), q3 + iqr_k * (q3 - q1)
        for idx, value in valid.items():
            z = (value - mean) / std if std else 0.0
            if abs(z) >= z_limit or value < lo or value > hi:
                row = df.loc[idx]
                label = str(row[ctx.date_column()]) if ctx.date_column() in df.columns else f"第 {int(idx) + 1} 行"
                found.append({
                    "定位": label, "字段": col, "数值": round(float(value), 2),
                    "Z值": round(float(z), 2),
                    "规则": "Z-score" if abs(z) >= z_limit else "IQR 围栏",
                })
    found.sort(key=lambda r: abs(r["Z值"]), reverse=True)
    top = found[:10]
    ratio = len(found) / len(df) * 100 if len(df) else 0
    facts = [
        f"采用 IQR {iqr_k:g} 倍围栏与 |Z| ≥ {z_limit:g} 双重规则，在 {len(targets[:6])} 个数值字段中"
        f"识别 {len(found)} 条异常（占全量 {ratio:.1f}%）。"
    ]
    if top:
        facts.append(f"偏离最大的是 {top[0]['定位']} 的 {top[0]['字段']}={top[0]['数值']}（Z={top[0]['Z值']}）。")
    return {
        "tool": "anomaly", "metrics": [
            {"k": "异常记录", "v": f"{len(found)} 条"},
            {"k": "异常占比", "v": f"{ratio:.1f}%"},
            {"k": "检查字段", "v": f"{len(targets[:6])} 个"},
            {"k": "最大偏离", "v": f"{abs(top[0]['Z值']):.2f} σ" if top else "—"},
        ],
        "facts": facts,
        "table": {"columns": ["定位", "字段", "数值", "Z值", "规则"], "rows": top},
    }


SPEC = ToolSpec(
    name="anomaly",
    description="用 IQR 围栏与 Z-score 检测数值字段中的异常记录，返回具体行与偏离程度。",
    parameters=object_schema({
        "metric": {"type": "string", "description": "要检查的数值列，留空检查全部数值列"},
        "z_threshold": {"type": "number", "description": "Z 阈值，默认 2.5"},
        "iqr_k": {"type": "number", "description": "IQR 倍数，默认 3.0"},
    }),
    handler=run,
)
