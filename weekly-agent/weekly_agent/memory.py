"""课程周报智能体 · 记忆层

三层结构：短期记忆（内存）、长期记忆（JSON 落盘）、反思记忆（交付后写回）。
检索只召回相关片段，避免把全部历史塞回上下文。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MEMORY: dict[str, Any] = {
    "members": [],
    "terms": [],
    "unfinished": [],
    "reflections": [],
    "history": [],
}


class MemoryStore:
    """长期记忆存储。所有读写都落盘，便于跨周复用。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else dict(DEFAULT_MEMORY)
        for key, value in DEFAULT_MEMORY.items():
            self.data.setdefault(key, value if not isinstance(value, list) else [])

    def recall(self, query: str = "", top_k: int = 5) -> list[dict[str, str]]:
        from .tools import retrieve_memory

        return retrieve_memory(self.data, query=query, top_k=top_k)["hits"]

    def add_reflection(self, note: str) -> None:
        if note and note not in self.data["reflections"]:
            self.data["reflections"].append(note)
            self.data["reflections"] = self.data["reflections"][-20:]

    def add_unfinished(self, items: list[str]) -> None:
        merged = list(dict.fromkeys([*self.data["unfinished"], *items]))
        self.data["unfinished"] = merged[-30:]

    def archive(self, week: str, summary: str) -> None:
        self.data["history"].append({"week": week, "summary": summary})
        self.data["history"] = self.data["history"][-12:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")