"""配置对象：YAML 内容 + dataclass 结构 → 全局单一配置源。

遵循教程第 4 章的加载链路：

    conf/app_config.yaml
      -> OmegaConf.load            读取配置内容
      -> OmegaConf.structured      准备配置结构（dataclass schema）
      -> OmegaConf.merge           合并结构与内容
      -> OmegaConf.to_object       转成 app_config.xxx.yyy 可直接访问的对象

路径用 ``Path(__file__).resolve().parents[2]`` 从当前文件回到 backend/ 根目录，
不依赖进程启动时的工作目录。密钥不写进 YAML，只由 .env / 环境变量注入 Secrets。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from omegaconf import OmegaConf

ROOT = Path(__file__).resolve().parents[2]  # backend/
CONFIG_FILE = ROOT / "conf" / "app_config.yaml"
PROMPTS_DIR = ROOT / "prompts"
LOGS_DIR = ROOT / "logs"

load_dotenv(ROOT / ".env", override=False)


# ---------------------------------------------------------------- 配置结构
@dataclass
class ConsoleLogConfig:
    enable: bool
    level: str


@dataclass
class FileLogConfig:
    enable: bool
    level: str
    path: str
    rotation: str
    retention: str


@dataclass
class LoggingConfig:
    console: ConsoleLogConfig
    file: FileLogConfig


@dataclass
class ProjectConfig:
    name: str
    env: str
    timezone: str


@dataclass
class ServerConfig:
    host: str
    port: int
    cors_origins: List[str]


@dataclass
class DBConfig:
    path: str
    dialect: str
    wal: bool


@dataclass
class EmbeddingConfig:
    provider: str
    dimension: int
    model: Optional[str]


@dataclass
class RetrievalConfig:
    top_k_per_route: int
    rrf_k: int
    final_top_k: int
    fts_enabled: bool
    keywords_top_k: int


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    model: str
    temperature: float
    timeout_s: int
    max_retries: int


@dataclass
class AgentConfig:
    mode: str
    engine: str
    max_steps: int
    step_timeout_s: int
    total_timeout_s: int
    max_sql_corrections: int
    max_rows: int
    mcp_enabled: bool


@dataclass
class MetaKnowledgeConfig:
    config_path: str


@dataclass
class AppConfig:
    project: ProjectConfig
    logging: LoggingConfig
    server: ServerConfig
    db: DBConfig
    embedding: EmbeddingConfig
    retrieval: RetrievalConfig
    llm: LLMConfig
    agent: AgentConfig
    meta_knowledge: MetaKnowledgeConfig


def _load() -> AppConfig:
    context = OmegaConf.load(CONFIG_FILE)
    schema = OmegaConf.structured(AppConfig)
    return OmegaConf.to_object(OmegaConf.merge(schema, context))  # type: ignore[return-value]


app_config: AppConfig = _load()


# ---------------------------------------------------------------- 密钥与覆盖
def env(*names: str, default: Optional[str] = None) -> Optional[str]:
    """按优先级读取环境变量（兼容用户原始命名 aliQwen-api）。"""
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return default


@dataclass(frozen=True)
class Secrets:
    """仅在内存中持有，禁止写入日志、事件、异常或任何文件。"""
    llm_api_key: Optional[str]

    @property
    def has_llm_key(self) -> bool:
        return bool(self.llm_api_key)


secrets = Secrets(llm_api_key=env("ALIQWEN_API_KEY", "aliQwen-api"))


def effective_mode() -> str:
    """环境变量优先于 YAML；缺密钥时真模型自动降级为 mock。"""
    mode = (env("LLM_MODE", default=app_config.agent.mode) or "mock").lower()
    if mode not in ("real", "mock"):
        mode = "mock"
    if mode == "real" and not secrets.has_llm_key:
        mode = "mock"
    return mode


def resolve_data_dir() -> Path:
    raw = env("APP_DATA_DIR", default="") or app_config.db.path
    # db.path 是相对 data/agent.db；取它的父目录作为数据目录
    p = Path(raw)
    if p.suffix == ".db":
        p = p.parent
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


__all__ = [
    "ROOT", "CONFIG_FILE", "PROMPTS_DIR", "LOGS_DIR",
    "AppConfig", "app_config", "Secrets", "secrets",
    "env", "effective_mode", "resolve_data_dir",
]
