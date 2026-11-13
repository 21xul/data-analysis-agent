"""引用收集器：记录本次回答引用了哪些口径文档，便于结论溯源。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CitationCollector:
    _seen: dict[str, dict] = field(default_factory=dict)

    def add_many(self, hits: list[dict]) -> None:
        for hit in hits:
            self._seen[hit["id"]] = {"id": hit["id"], "title": hit["title"], "kind": hit["kind"]}

    def as_list(self) -> list[dict]:
        return list(self._seen.values())
