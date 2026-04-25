"""GraphMemory SQLite backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.graph_memory import GraphMemory


@pytest.mark.asyncio
async def test_graph_memory_sqlite_merge_and_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ADAMI_GRAPH_MEMORY_SQLITE_PATH", str(tmp_path / "g.db"))
    g = GraphMemory()
    assert g.enabled
    await g.initialize()
    assert g.enabled
    await g.merge_knowledge(
        [
            {"id": "A", "type": "Tool", "name": "A"},
            {"id": "B", "type": "Tool", "name": "B"},
        ],
        [{"source": "A", "target": "B", "relation": "USES"}],
    )
    rows = await g.query_subgraph("A", hops=2, limit=10)
    assert any(r.get("target") == "B" for r in rows)
    from_b = await g.query_subgraph("B", hops=2, limit=10)
    assert any(r.get("target") == "A" for r in from_b)
    await g.close()
