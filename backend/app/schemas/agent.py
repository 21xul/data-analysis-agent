"""Agent 请求契约（Pydantic → OpenAPI）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500, description="自然语言分析问题")
    dataset_id: str = Field(..., min_length=1, description="已上传的数据集 id")


class DemoRequest(BaseModel):
    rows: int = Field(48, ge=6, le=240)


class GraphRunRequest(BaseModel):
    """LangGraph 编排入口契约（P0：同步返回完整节点轨迹）。"""
    question: str = Field(..., min_length=2, max_length=500)
    dataset_id: str = Field("", description="可选；ReAct 分支调用确定性工具时需要")
    force_branch: str = Field("", pattern="^(|sql|react)$",
                              description="留空按意图自动路由；测试可强制 sql / react")
