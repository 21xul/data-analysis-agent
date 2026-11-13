"""v1 路由汇总。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import agent, datasets, graph, health

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(datasets.router)
router.include_router(agent.router)       # 原 ReAct SSE 链路
router.include_router(graph.router)       # LangGraph 编排链路（P0）
