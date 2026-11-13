"""统一错误类型：把领域错误与 HTTP 状态码解耦。"""
from __future__ import annotations


class AppError(Exception):
    code = "app_error"
    status = 400

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class DatasetNotFound(AppError):
    code = "dataset_not_found"
    status = 404


class ToolError(AppError):
    code = "tool_error"


class UnknownTool(ToolError):
    code = "unknown_tool"


class GuardrailError(AppError):
    code = "guardrail_violation"


class LLMUnavailable(AppError):
    code = "llm_unavailable"
    status = 503


class MCPError(AppError):
    code = "mcp_error"
