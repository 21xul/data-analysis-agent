"""数据集上传、注册、列表、示例数据与预览。

P1：上传/示例数据保存后**自动注册**成 ``ds_<id>`` 只读物理表，并增量同步元数据
（字段语义 + 文本取值）进知识库，这样 SQL 分支与三路召回立刻可用，无需重启后端。
"""
from __future__ import annotations

import io
import uuid

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile

from app.bootstrap import dataframe_to_payload
from app.core.errors import DatasetNotFound
from app.infra import dataset_repo
from app.schemas.agent import DemoRequest
from app.services import dataset_registry as DR
from app.services import dataset_stats as DS
from app.services.meta_knowledge_service import sync_dataset

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _read_csv(raw: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise HTTPException(400, "无法解析 CSV，请检查文件编码与格式")


def _register(conn, ds_id: str) -> dict:
    """唯一的注册入口：物理表 + 注册登记 + 元数据增量同步。"""
    try:
        schema = DR.ensure_registered(conn, ds_id)
        sync_dataset(conn, ds_id)
    except DatasetNotFound as exc:
        raise HTTPException(404, exc.message) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return schema


@router.post("")
async def upload(request: Request, file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件超过 10 MB 上限")
    df = _read_csv(raw)
    if df.empty or len(df.columns) == 0:
        raise HTTPException(400, "文件没有可分析的数据")
    payload = dataframe_to_payload(df, file.filename or "未命名数据集")
    ds_id = dataset_repo.save(request.app.state.db, payload["name"], payload)
    schema = _register(request.app.state.db, ds_id)
    return {"id": ds_id, "name": payload["name"], "rows": len(df),
            "columns": payload["columns"], "table": schema["table"], "registered": True}


@router.get("")
def list_datasets(request: Request) -> list[dict]:
    return dataset_repo.list_all(request.app.state.db)


@router.post("/demo")
def create_demo(request: Request, body: DemoRequest | None = None) -> dict:
    """生成一份带已知异常尖峰的示例数据，便于零配置验证全链路。"""
    import numpy as np

    n = (body.rows if body else 48)
    rng = np.random.default_rng(2026)
    channels = ["线上", "线下", "分销"]
    dates = pd.date_range("2025-01-01", periods=n // 3, freq="MS")
    records = []
    for d in dates:
        for ch in channels:
            base = {"线上": 120000, "线下": 86000, "分销": 54000}[ch]
            sales = base * (1 + 0.035 * (d.month - 1)) + rng.normal(0, 4200)
            if d.month == 8 and ch == "线上":
                sales *= 2.35  # 植入一处可定位的异常
            records.append({
                "日期": d.strftime("%Y-%m-%d"),
                "渠道": ch,
                "销售额": round(float(sales), 2),
                "订单数": int(abs(sales / 320 + rng.normal(0, 18))),
                "退款率": round(float(abs(rng.normal(1.6, 0.4))), 2),
            })
    df = pd.DataFrame(records)
    payload = dataframe_to_payload(df, "2025 电商渠道示例数据")
    ds_id = dataset_repo.save(request.app.state.db, payload["name"],
                              dict(payload, id=f"demo_{uuid.uuid4().hex[:6]}"))
    schema = _register(request.app.state.db, ds_id)
    return {"id": ds_id, "name": payload["name"], "rows": len(df),
            "columns": payload["columns"], "table": schema["table"], "registered": True}


@router.post("/{dataset_id}/register")
def register_dataset(dataset_id: str, request: Request) -> dict:
    """手动重注册（数据被外部改动时可重放）；幂等。"""
    schema = _register(request.app.state.db, dataset_id)
    return {"registered": True, **schema}


@router.get("/{dataset_id}/schema")
def dataset_schema(dataset_id: str, request: Request) -> dict:
    """SQL 分支看到的执行靶：表名 + 列 + 类型 + 样例取值。"""
    try:
        return DR.schema_for(request.app.state.db, dataset_id)
    except DatasetNotFound as exc:
        raise HTTPException(404, exc.message) from exc


@router.get("/{dataset_id}/stats")
def stats(dataset_id: str, request: Request) -> dict:
    """工作台概览卡：确定性统计，前端不自行估算。"""
    return DS.compute(dataset_repo.get(request.app.state.db, dataset_id))


@router.get("/{dataset_id}/preview")
def preview(dataset_id: str, request: Request,
            limit: int = Query(40, ge=1, le=200)) -> dict:
    """数据预览：默认前 40 行；limit 上限 200 行，避免一次拖回整个载荷。"""
    ds = dataset_repo.get(request.app.state.db, dataset_id)
    rows = ds["rows"]
    return {"id": dataset_id, "name": ds["name"], "columns": ds["columns"],
            "rows": rows[:limit], "total": len(rows), "shown": min(limit, len(rows))}


@router.delete("/{dataset_id}")
def remove(dataset_id: str, request: Request) -> dict:
    conn = request.app.state.db
    DR.unregister(conn, dataset_id)
    return {"deleted": dataset_repo.remove(conn, dataset_id)}
