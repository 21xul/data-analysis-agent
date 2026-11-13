"""静态提示词加载器：读取 backend/prompts/*.md，做极简变量替换。

教程第 4 章约定「提示词放源码目录之外」；这里把模板内容从 Python 代码里彻底剥离，
planner / SQL 生成节点只负责传变量，不内嵌大段 prompt 文本。
"""
from __future__ import annotations

from pathlib import Path

from app.conf.app_config import PROMPTS_DIR

_CACHE: dict[str, str] = {}


def load(name: str, **variables: object) -> str:
    """加载模板；``{{key}}`` 用传入变量替换，缺失变量保留占位符以便排查。"""
    key = name if name.endswith(".md") else f"{name}.md"
    if key not in _CACHE:
        path: Path = PROMPTS_DIR / key
        if not path.exists():
            raise FileNotFoundError(f"prompt not found: {path}")
        _CACHE[key] = path.read_text(encoding="utf-8")
    text = _CACHE[key]
    for k, v in variables.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def available() -> list[str]:
    return sorted(p.name for p in PROMPTS_DIR.glob("*.md"))


__all__ = ["load", "available"]
