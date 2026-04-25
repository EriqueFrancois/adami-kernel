# 文件路径：src/adami_kernel/telemetry/experience_aggregator.py
"""Episode 汇聚与按日落盘（与 AGL 解耦）。

设计说明（存储形态）
------------------
- **默认（本实现）**：``<ADAMI_EXPERIENCE_DIR> / YYYY-MM-DD / episodes.jsonl``，
  每行一条完整 Episode 的 JSON，便于按日压缩与批处理训练管线。
- **备选**：按 ``trace_id`` 单文件 ``.../YYYY-MM-DD/episodes/<trace_id>.jsonl``，
  适合极长 episode 或合规「单会话导出」；首版未启用，以降低 inode 与小文件数量。
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t

logger = logging.getLogger("AdamI-ExperienceAggregator")


def _expag_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class ExperienceAggregator:
    """线程安全：缓冲未完成 Episode 的事件，finalize 时追加写入 jsonl。"""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir)
        self._lock = threading.Lock()
        # episode_id -> { "primary_trace_id", "started_at", "meta", "events" }
        self._open: Dict[str, Dict[str, Any]] = {}

    def _ensure_unlocked(
        self,
        episode_id: str,
        primary_trace_id: str,
        *,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if episode_id in self._open:
            if meta:
                self._open[episode_id].setdefault("meta", {}).update(meta)
            return
        self._open[episode_id] = {
            "primary_trace_id": primary_trace_id,
            "started_at": datetime.now(timezone.utc).timestamp(),
            "meta": dict(meta or {}),
            "events": [],
        }

    def ensure_episode(
        self,
        episode_id: str,
        primary_trace_id: str,
        *,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self._ensure_unlocked(episode_id, primary_trace_id, meta=meta)

    def add_event(self, episode_id: str, event: Dict[str, Any]) -> int:
        """将单条事件并入 episode，返回分配的 turn_index。"""
        with self._lock:
            if episode_id not in self._open:
                self._ensure_unlocked(episode_id, event.get("trace_id") or episode_id, meta={})
            bucket = self._open[episode_id]
            turn_index = len(bucket["events"])
            ev = dict(event)
            ev["turn_index"] = int(ev.get("turn_index", turn_index))
            bucket["events"].append(ev)
            return turn_index

    def finalize_episode(
        self,
        episode_id: str,
        status: str,
        *,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """序列化 Episode 为单行 JSON 写入当日 episodes.jsonl。"""
        with self._lock:
            bucket = self._open.pop(episode_id, None)
        if bucket is None:
            logger.debug(_expag_t("expag.debug.finalize_skip", eid=episode_id))
            return

        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir = self._base_dir / day
        try:
            day_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(_expag_t("expag.warn.mkdir", path=day_dir, e=e))
            return

        out_path = day_dir / "episodes.jsonl"
        ended_at = datetime.now(timezone.utc).timestamp()
        meta = dict(bucket.get("meta") or {})
        if extra_meta:
            meta.update(extra_meta)

        doc: Dict[str, Any] = {
            "episode_id": episode_id,
            "primary_trace_id": bucket.get("primary_trace_id"),
            "started_at": bucket.get("started_at"),
            "ended_at": ended_at,
            "status": status,
            "meta": meta,
            "events": bucket.get("events") or [],
        }

        line = json.dumps(doc, ensure_ascii=False, default=str) + "\n"
        try:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            logger.warning(_expag_t("expag.warn.write", path=out_path, e=e))
