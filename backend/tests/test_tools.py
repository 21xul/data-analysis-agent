"""确定性工具回归测试：直接用 python tests/test_tools.py 运行，无需 pytest。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools import anomaly, compare, profile, query, trend  # noqa: E402
from app.tools.registry import ToolContext  # noqa: E402


def make_ctx() -> ToolContext:
    df = pd.DataFrame({
        "日期": ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01"] * 2,
        "渠道": ["线上", "线上", "线上", "线上", "线下", "线下", "线下", "线下"],
        "销售额": [100.0, 110.0, 120.0, 900.0, 80.0, 85.0, 90.0, 95.0],
        "订单数": [10, 11, 12, 13, 8, 9, 9, 10],
    })
    df["日期"] = pd.to_datetime(df["日期"])
    columns = [
        {"label": "日期", "type": "date"}, {"label": "渠道", "type": "text"},
        {"label": "销售额", "type": "number"}, {"label": "订单数", "type": "number"},
    ]
    return ToolContext(frame=df, dataset_name="测试集", columns=columns)


def main() -> None:
    ctx = make_ctx()
    p = profile.run(ctx, {})
    assert "8 行" in p["metrics"][0]["v"], p

    t = trend.run(ctx, {"metric": "销售额"})
    assert len(t["values"]) == 4, t
    assert t["chart"]["type"] == "line", t

    a = anomaly.run(ctx, {"metric": "销售额"})
    assert a["metrics"][0]["v"].endswith("条"), a

    c = compare.run(ctx, {"metric": "销售额"})
    assert c["metrics"][1]["v"] == "线上", c

    q = query.run(ctx, {"filters": [{"column": "销售额", "op": "gt", "value": 100}], "limit": 3})
    assert len(q["table"]["rows"]) == 3, q
    assert q["metrics"][0]["v"] == "3 行", q  # 100、110、120、900、80、85、90、95 中 >100 的共 3 行

    print("PASS test_tools · profile/trend/anomaly/compare/query 全部通过")


if __name__ == "__main__":
    main()
