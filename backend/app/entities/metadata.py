"""元数据知识库的业务实体（教程 2.2 四张核心表 + 取值 / 向量 / 命中结果）。

entities 与 models 分开：这里表达「业务上是什么」，models/meta_schema.py 只管「怎么存」。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TableInfo:
    id: str
    name: str
    role: str = "dim"                 # fact | dim | dataset
    description: str = ""
    source: str = "builtin"           # builtin | uploaded


@dataclass
class ColumnInfo:
    id: str
    table_id: str
    name: str
    type: str = "text"
    role: str = "dimension"           # primary_key | foreign_key | dimension | measure
    description: str = ""
    alias: list[str] = field(default_factory=list)
    examples: list[Any] = field(default_factory=list)
    index_value: bool = False         # 文本型维度字段才建全文取值索引


@dataclass
class MetricInfo:
    id: str
    name: str
    description: str = ""
    relevant_columns: list[str] = field(default_factory=list)
    alias: list[str] = field(default_factory=list)


@dataclass
class ColumnMetric:
    column_id: str
    metric_id: str


@dataclass
class ValueInfo:
    id: str
    value: str
    column_id: str
    table_id: str


@dataclass
class VectorPoint:
    """一行元数据对应多个向量点：name / description / 每个 alias 各一个。"""
    id: str
    ref_type: str                     # column | metric
    ref_id: str
    field: str                        # name | description | alias[0] ...
    text: str
    vector: list[float]


@dataclass
class RecallHit:
    ref_type: str                     # column | metric | value
    ref_id: str
    score: float
    source: str                       # vector | fts | structured
    payload: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "TableInfo", "ColumnInfo", "MetricInfo", "ColumnMetric",
    "ValueInfo", "VectorPoint", "RecallHit",
]
