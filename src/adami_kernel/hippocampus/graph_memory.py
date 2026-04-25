# src/adami_kernel/hippocampus/graph_memory.py
"""图谱记忆：仅 SQLite 嵌入式后端（``graph_memory.db``，实现见 ``graph_memory_sqlite``）。"""

from __future__ import annotations

from adami_kernel.hippocampus.graph_memory_sqlite import GraphMemorySqlite as GraphMemory

__all__ = ["GraphMemory"]
