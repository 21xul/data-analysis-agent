"""端到端冒烟：mock 模式下跑完一次完整 ReAct 链路。

python tests/test_agent_smoke.py
不联网、不消耗模型额度、不写入真实凭据。
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bootstrap import build_context, build_registry  # noqa: E402
from app.core.agent.guardrails import Guardrails  # noqa: E402
from app.core.agent.loop import run_agent  # noqa: E402
from app.core.agent.planner import Planner  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.infra import dataset_repo  # noqa: E402
from app.infra.llm_client import LLMClient  # noqa: E402
from app.infra.sqlite import connect, init_db  # noqa: E402


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "smoke.db")
        init_db(conn)
        payload = {
            "name": "冒烟数据集",
            "columns": [
                {"key": "日期", "label": "日期", "type": "date"},
                {"key": "渠道", "label": "渠道", "type": "text"},
                {"key": "销售额", "label": "销售额", "type": "number"},
                {"key": "订单数", "label": "订单数", "type": "number"},
            ],
            "rows": [
                {"日期": f"2025-{m:02d}-01", "渠道": ch,
                 "销售额": 100 + m * 10 + (500 if m == 8 and ch == "线上" else 0) + (0 if ch == "线上" else -30),
                 "订单数": 10 + m}
                for m in range(1, 10) for ch in ("线上", "线下")
            ],
        }
        ds_id = dataset_repo.save(conn, payload["name"], payload)
        ctx = build_context(conn, ds_id)
        ctx.extras["question"] = "分析销售额的月度趋势"
        registry = build_registry(conn)
        planner = Planner(LLMClient(settings), "mock")
        guard = Guardrails(allowed=set(registry.names()), max_steps=settings.max_steps)

        kinds: list[str] = []
        final = None
        async for ev in run_agent(
            question="分析销售额的月度趋势", ctx=ctx, registry=registry,
            planner=planner, guard=guard, conn=conn, settings=settings,
        ):
            kinds.append(ev["type"])
            if ev["type"] == "final":
                final = ev["data"]
            print(f"  [{ev['type']}] " + str(ev["data"])[:110])

        for required in ("meta", "rag", "thought", "action", "observation", "final"):
            assert required in kinds, f"缺少事件 {required}"
        assert final and final["conclusions"], "未产出结论"
        assert final["mode"] == "mock", final
        print(f"PASS test_agent_smoke · {len(kinds)} 个事件 · {len(final['conclusions'])} 条结论")
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
