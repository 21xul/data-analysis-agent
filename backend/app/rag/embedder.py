"""确定性本地 embedding：字符 n-gram 哈希到固定维度。

原型阶段零外部依赖、零 API 调用；切换到真 embedding 模型时只替换本文件。
"""
from __future__ import annotations

import hashlib
import re

DIM = 256
_WORD = re.compile(r"[A-Za-z0-9_]+")
_HAN = re.compile(r"[\u4e00-\u9fff]")


def _bucket(token: str) -> int:
    return int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % DIM


def embed(text: str) -> list[float]:
    s = str(text or "").lower()
    tokens: list[str] = list(_WORD.findall(s))
    han = _HAN.findall(s)
    tokens.extend(han)
    tokens.extend(a + b for a, b in zip(han, han[1:]))
    vec = [0.0] * DIM
    for token in tokens:
        vec[_bucket(token)] += 1.0
    # L2 归一化，便于直接用点积做余弦
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else vec
