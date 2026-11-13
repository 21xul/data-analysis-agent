"""Embedding 客户端：C 路线用本地确定性哈希向量，接口可替换为 HF / 远端模型。

教程把 TEI 单独部署成服务；本地原型里等价收敛成这一个可插拔函数，
服务层只调用 embed()，不关心底层是哈希还是模型。
"""
from __future__ import annotations

import math

from app.conf.app_config import app_config
from app.rag.embedder import embed as _hash_embed

__all__ = ["embed", "cosine", "dimension"]


def dimension() -> int:
    return int(app_config.embedding.dimension)


def embed(text: str) -> list[float]:
    vec = _hash_embed(text)
    if len(vec) != dimension():
        raise RuntimeError(
            f"embedding dimension mismatch: got {len(vec)}, config expects {dimension()}"
        )
    if app_config.embedding.provider == "huggingface":
        # 预留：装好 langchain_huggingface + 本地模型后在此分支替换实现。
        # C 路线默认不启用，避免下载 1.3GB 模型、破坏零外部服务约束。
        pass
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
