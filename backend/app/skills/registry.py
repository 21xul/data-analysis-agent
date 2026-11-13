"""技能注册表：扫描 skills/*/manifest.yaml，把技能包装成标准 ToolSpec。

说明：WorkBuddy 工作台的 Skill 属于 IDE 侧运行时，不能嵌入 FastAPI 进程；
这里是应用内同构的「技能包」概念，遵守同样的 manifest/prompt/handler 约定。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import yaml

from app.tools.registry import ToolRegistry, ToolSpec

SKILLS_DIR = Path(__file__).resolve().parent


def _load_handler(skill_dir: Path, name: str) -> ModuleType:
    path = skill_dir / "handler.py"
    spec = importlib.util.spec_from_file_location(f"insight_skill_{name}", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"无法加载技能 {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def register_all(registry: ToolRegistry) -> list[str]:
    loaded: list[str] = []
    for manifest_path in sorted(SKILLS_DIR.glob("*/manifest.yaml")):
        skill_dir = manifest_path.parent
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        name = str(manifest.get("name") or skill_dir.name)
        enabled = manifest.get("enabled", True)
        if not enabled:
            continue
        module = _load_handler(skill_dir, name)
        spec = ToolSpec(
            name=f"skill__{name}",
            description=str(manifest.get("description") or f"执行领域技能 {name}"),
            parameters=manifest.get("parameters") or {"type": "object", "properties": {}},
            handler=module.run,
            readonly=bool(manifest.get("readonly", True)),
        )
        registry.register(spec)
        loaded.append(spec.name)
    return loaded
