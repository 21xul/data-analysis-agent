"""数据集概览统计（确定性服务，不经过模型）。

工作台顶部 5 张统计卡与结论卡里的「数据概览与质量」都消费本模块的输出：
逐行扫描保存的 JSON 载荷，避免前端用抽样行估算导致口径不一致。
与 Agent 的分析结论无关，只描述数据集本身。
"""
from __future__ import annotations

import json
from typing import Any

_ID_LIKE = ("学号", "编号", "序号", "id", "编码")


def _empty(value: Any) -> bool:
    """缺失值口径：None / 空串 / NaN，与 v1 前端保持一致。"""
    if value is None or value == "":
        return True
    return isinstance(value, float) and value != value  # NaN


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def compute(ds: dict[str, Any]) -> dict[str, Any]:
    """返回工作台概览所需的全部标量统计。"""
    rows: list[dict[str, Any]] = ds.get("rows") or []
    columns: list[dict[str, Any]] = ds.get("columns") or []
    keys = [c.get("key") or c.get("label") for c in columns]
    labels = {c.get("key") or c.get("label"): c.get("label") for c in columns}

    numeric = [c for c in columns if c.get("type") == "number"]
    dates = [c for c in columns if c.get("type") == "date"]
    texts = [c for c in columns if c.get("type") not in ("number", "date")]

    missing = sum(1 for row in rows for key in keys if _empty(row.get(key)))
    cells = len(rows) * len(keys)
    completeness = round((1 - missing / cells) * 100, 1) if cells else 100.0

    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        fingerprint = _dump([row.get(key) for key in keys])
        if fingerprint in seen:
            duplicates += 1
        else:
            seen.add(fingerprint)

    size_kb = round(len(_dump(rows).encode("utf-8")) / 1024, 1)

    metric_cols = [c for c in numeric
                   if not any(word in str(c.get("label", "")).lower() for word in _ID_LIKE)]
    primary_metric = labels.get((metric_cols or numeric)[0].get("key")) if (metric_cols or numeric) else None
    primary_dimension = labels.get(texts[0].get("key")) if texts else None

    date_range = ""
    if dates:
        key = dates[0].get("key") or dates[0].get("label")
        values = sorted(str(row.get(key) or "") for row in rows if row.get(key))
        values = [v for v in values if v[:4].isdigit()]
        if values:
            date_range = f"{values[0][:10]} ~ {values[-1][:10]}"

    return {
        "name": ds.get("name") or "未命名数据集",
        "rows": len(rows),
        "columns": len(columns),
        "numeric": len(numeric),
        "dates": len(dates),
        "texts": len(texts),
        "primary_metric": primary_metric,
        "primary_dimension": primary_dimension,
        "missing": missing,
        "completeness": completeness,
        "duplicates": duplicates,
        "size_kb": size_kb,
        "date_range": date_range,
        "storage": "SQLite · 本地原型",
    }


__all__ = ["compute"]
