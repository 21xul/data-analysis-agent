"""薄适配层：把单一配置源映射成旧的 Settings 接口。

配置内容、结构与密钥都在 ``app/conf/app_config.py``（conf/app_config.yaml + .env）。
本文件只保留既有模块依赖的字段名，避免目录重组时改动十几处调用点。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.conf.app_config import app_config, effective_mode, env, resolve_data_dir, secrets


@dataclass(frozen=True)
class Settings:
    llm_mode: str                     # "real" | "mock"
    api_key: str | None               # 仅内存持有，永不写日志
    base_url: str
    model: str
    data_dir: Path
    db_path: Path
    max_steps: int
    step_timeout_s: float
    total_timeout_s: float
    mcp_enabled: bool
    engine: str                       # "react" | "langgraph"
    max_sql_corrections: int
    max_rows: int

    @property
    def real_llm_ready(self) -> bool:
        return self.llm_mode == "real" and bool(self.api_key)


def _num(name: str, default: object) -> float:
    raw = env(name, default=str(default))
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return float(str(default))


def _flag(name: str, default: bool) -> bool:
    raw = env(name, default=str(default))
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def get_settings() -> Settings:
    data_dir = resolve_data_dir()
    db_name = Path(app_config.db.path).name
    db_path = Path(env("APP_DB_PATH", default="") or (data_dir / db_name))
    if not db_path.is_absolute():
        db_path = (data_dir / db_path).resolve()

    return Settings(
        llm_mode=effective_mode(),
        api_key=secrets.llm_api_key,
        base_url=env("ALIQWEN_BASE_URL", default=app_config.llm.base_url) or "",
        model=env("ALIQWEN_MODEL", default=app_config.llm.model) or "",
        data_dir=data_dir,
        db_path=db_path,
        max_steps=int(_num("AGENT_MAX_STEPS", app_config.agent.max_steps)),
        step_timeout_s=float(_num("AGENT_STEP_TIMEOUT", app_config.agent.step_timeout_s)),
        total_timeout_s=float(_num("AGENT_TOTAL_TIMEOUT", app_config.agent.total_timeout_s)),
        mcp_enabled=_flag("MCP_ENABLED", app_config.agent.mcp_enabled),
        engine=(env("AGENT_ENGINE", default=app_config.agent.engine) or "react").lower(),
        max_sql_corrections=int(_num("AGENT_MAX_SQL_CORRECTIONS", app_config.agent.max_sql_corrections)),
        max_rows=int(_num("AGENT_MAX_ROWS", app_config.agent.max_rows)),
    )


settings = get_settings()
