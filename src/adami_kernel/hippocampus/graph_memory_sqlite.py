"""Embedded graph memory backed by SQLite (no Bolt server or password)."""

from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-GraphMemory")


def _gmem_t(key: str, **kwargs: Any) -> str:  # noqa: ANN401
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class GraphMemorySqlite:
    """Entity/relationship graph stored under ``ADAMI_DATA_DIR`` (or ``ADAMI_GRAPH_MEMORY_SQLITE_PATH``)."""

    def __init__(self) -> None:
        raw = getattr(settings, "ADAMI_GRAPH_MEMORY_SQLITE_PATH", None)
        if raw and str(raw).strip():
            self._path = Path(str(raw).strip()).expanduser()
        else:
            self._path = settings.adami_data_dir_path / "graph_memory.db"
        self._conn: Optional[aiosqlite.Connection] = None
        self.enabled = True

    async def initialize(self) -> None:
        if not self.enabled:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(self._path))
            self._conn.row_factory = aiosqlite.Row
            await self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS gmem_entities (
                    id TEXT PRIMARY KEY NOT NULL,
                    type TEXT NOT NULL DEFAULT 'Unknown',
                    name TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gmem_relationships (
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    rel_type TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (source, target, rel_type)
                );
                CREATE INDEX IF NOT EXISTS idx_gmem_rel_source ON gmem_relationships(source);
                CREATE INDEX IF NOT EXISTS idx_gmem_rel_target ON gmem_relationships(target);
                """
            )
            await self._conn.commit()
            logger.info(_gmem_t("gmem.log.sqlite_ready", path=str(self._path)))
        except Exception as e:
            logger.warning(_gmem_t("gmem.warn.sqlite_init", e=e))
            self.enabled = False
            if self._conn:
                await self._conn.close()
                self._conn = None

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info(_gmem_t("gmem.log.sqlite_closed"))

    async def merge_knowledge(
        self, entities: List[Dict[str, Any]], relationships: List[Dict[str, Any]]
    ) -> None:
        if not self.enabled or not self._conn:
            return
        now = time.time()
        try:
            await self._conn.execute("BEGIN IMMEDIATE")
            for entity in entities:
                eid = str(entity.get("id") or "").strip()
                if not eid:
                    continue
                await self._conn.execute(
                    """
                    INSERT INTO gmem_entities (id, type, name, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        type=excluded.type,
                        name=excluded.name,
                        updated_at=excluded.updated_at
                    """,
                    (
                        eid,
                        str(entity.get("type") or "Unknown"),
                        str(entity.get("name") or eid),
                        now,
                    ),
                )
            for rel in relationships:
                src = str(rel.get("source") or "").strip()
                tgt = str(rel.get("target") or "").strip()
                rtyp = str(rel.get("relation") or "RELATED").strip()
                if not src or not tgt:
                    continue
                await self._conn.execute(
                    """
                    INSERT INTO gmem_relationships (source, target, rel_type, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(source, target, rel_type) DO UPDATE SET
                        updated_at=excluded.updated_at
                    """,
                    (src, tgt, rtyp, now),
                )
            await self._conn.commit()
            logger.info(_gmem_t("gmem.log.merge_ok", ne=len(entities), nr=len(relationships)))
        except Exception as e:
            if self._conn:
                await self._conn.rollback()
            logger.error(_gmem_t("gmem.err.merge_fail", e=e))

    async def query_subgraph(
        self, start_entity: str, hops: int = 2, limit: int = 20
    ) -> List[Dict[str, Any]]:
        if not self.enabled or not self._conn:
            return []
        start = (start_entity or "").strip()
        if not start:
            return []
        try:
            records: List[Dict[str, Any]] = []
            visited: set[str] = {start}
            q: deque[tuple[str, int]] = deque([(start, 0)])
            while q and len(records) < limit:
                node, depth = q.popleft()
                if depth >= hops:
                    continue
                async with self._conn.execute(
                    "SELECT source, target, rel_type FROM gmem_relationships WHERE source = ? OR target = ?",
                    (node, node),
                ) as cur:
                    rows = await cur.fetchall()
                for row in rows:
                    src = str(row["source"])
                    tgt = str(row["target"])
                    rtyp = str(row["rel_type"])
                    other = tgt if src == node else src
                    records.append(
                        {
                            "source": node,
                            "target": other,
                            "relation": rtyp,
                            "nodes": None,
                        }
                    )
                    if len(records) >= limit:
                        return records
                    if other not in visited:
                        visited.add(other)
                        q.append((other, depth + 1))
            return records
        except Exception as e:
            logger.error(_gmem_t("gmem.err.subgraph", e=e))
            return []

    async def get_related_errors(self, skill_name: str) -> str:
        subgraph = await self.query_subgraph(skill_name, hops=2, limit=10)
        if not subgraph:
            return ""
        lines = [boot_t("cjk_gate.graph_memory_assoc_header")]
        for item in subgraph:
            lines.append(f"{item.get('source')} --[{item.get('relation')}]--> {item.get('target')}")
        return "\n".join(lines)
