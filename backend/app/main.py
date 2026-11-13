"""Insight Agent v2 · FastAPI 入口（本地原型，不发布）。

启动： uvicorn app.main:app --reload --port 8000 --app-dir backend
前端： cd frontend && npm install && npm run dev   (Vite :5173 代理 /api → :8000)

生命周期里同时完成两条主线：
  构建期：build_meta() 按 conf/meta_knowledge.yaml 重建元数据知识库
  查询期：build_graph() 编译 LangGraph 状态图，挂到 app.state 供路由使用
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import build_graph
from app.api.v1.router import router
from app.bootstrap import build_registry
from app.conf.app_config import app_config
from app.core.config import settings
from app.core.errors import AppError
from app.infra.sqlite import connect, init_db
from app.services.meta_knowledge_service import build as build_meta

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("insight")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect(settings.db_path)
    init_db(conn)                       # 业务表：datasets / analyses / runs / documents
    meta = build_meta(conn)             # 构建期：结构化元数据 + 向量 + FTS5
    app.state.db = conn
    app.state.meta = meta
    app.state.registry = build_registry(conn)
    app.state.graph = build_graph(conn, app.state.registry)
    # 凭据只在内存中使用；这里绝不打印 api_key / base_url 之外的敏感值
    log.info(
        "started · mode=%s · engine=%s · model=%s · tools=%d · meta(tables=%s, vectors=%s, values=%s)",
        settings.llm_mode, settings.engine,
        settings.model if settings.llm_mode == "real" else "-",
        len(app.state.registry.names()),
        meta.get("table_info"), meta.get("meta_vectors"), meta.get("value_info"),
    )
    yield
    conn.close()


app = FastAPI(title="Insight Agent v2", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.as_dict())


# 本地原型走 Vite dev server；若构建过 dist/ 则顺带同源托管，便于日后合并单端口
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(html=True, directory=str(DIST)), name="frontend")
