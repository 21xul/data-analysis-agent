"""健康检查与模型连通性自检（自检不回显任何凭据）。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.config import settings
from app.infra.llm_client import LLMClient
from app.rag.index import ensure_index

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    conn = request.app.state.db
    return {
        "status": "ok",
        "mode": settings.llm_mode,
        "model": settings.model if settings.llm_mode == "real" else None,
        "llm_ready": settings.real_llm_ready,
        "tools": request.app.state.registry.names(),
        "documents": ensure_index(conn),
        "mcp_enabled": settings.mcp_enabled,
    }


@router.get("/health/llm")
async def check_llm() -> dict:
    if not settings.real_llm_ready:
        return {"ok": False, "mode": "mock", "reason": "LLM_MODE 不是 real 或未配置密钥"}
    return await LLMClient(settings).check()
