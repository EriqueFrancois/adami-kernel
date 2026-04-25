from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.peripheral.report_studio.report_store import ReportConfigStore

logger = logging.getLogger("AdamI-ReportScheduler")


@dataclass
class _LastFired:
    date_key: str
    fired_at_ts: float


class ReportScheduler:
    """
    Phase 1 scheduler:
    - loads report configs from SecondBrain
    - checks timezone + HH:MM match
    - publishes system.events with `/report run <type>`
    """

    def __init__(self, event_bus: Any, *, default_chat_id: int = 5405872526) -> None:
        self.event_bus = event_bus
        self.default_chat_id = default_chat_id
        self._running = False
        self._last_fired: Dict[str, _LastFired] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._tick())

    async def stop(self) -> None:
        self._running = False

    def _local_now(self, tz_name: str, *, now_utc: Optional[datetime] = None) -> datetime:
        now = now_utc or datetime.now(timezone.utc)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        return now.astimezone(tz)

    def _due_now(self, *, cfg: Any, now_utc: Optional[datetime] = None) -> bool:
        if not getattr(cfg, "enabled", False):
            return False
        rt = str(getattr(cfg, "report_type", "") or "")
        sch = getattr(cfg, "schedule", None)
        if sch is None:
            return False
        local = self._local_now(str(getattr(sch, "timezone", "UTC") or "UTC"), now_utc=now_utc)
        hhmm = str(getattr(sch, "publish_time_hhmm", "09:00") or "09:00").strip()
        if local.strftime("%H:%M") != hhmm:
            return False
        # weekly/monthly gates
        if rt == "weekly":
            wd = getattr(sch, "weekday", None)
            if wd is not None and int(wd) != int(local.weekday()):
                return False
        if rt == "monthly":
            dom = getattr(sch, "day_of_month", None)
            if dom is not None and int(dom) != int(local.day):
                return False
        # cooldown: only once per local date for same report_type
        date_key = local.strftime("%Y-%m-%d")
        last = self._last_fired.get(rt)
        if last and last.date_key == date_key:
            return False
        return True

    async def _publish_run_event(self, report_type: str) -> None:
        task = f"/report run {report_type}"
        ev = AdamiEvent(
            trace_id=f"report_sched_{report_type}_{int(datetime.now(timezone.utc).timestamp())}",
            source_module="peripheral.report_scheduler",
            target_topic="system.events",
            priority=EventPriority.NORMAL,
            payload={"task": task, "chat_id": str(self.default_chat_id)},
        )
        await self.event_bus.publish(ev)

    async def _tick(self) -> None:
        sb = SecondBrainManager()
        store = ReportConfigStore(sb)
        # quick poll loop; later can compute next wake precisely
        while self._running:
            try:
                store.ensure_defaults()
                for rt in ("daily", "weekly", "monthly"):
                    cfg = store.load(rt)  # type: ignore[arg-type]
                    if self._due_now(cfg=cfg):
                        await self._publish_run_event(rt)
                        local = self._local_now(cfg.schedule.timezone)
                        self._last_fired[rt] = _LastFired(
                            date_key=local.strftime("%Y-%m-%d"),
                            fired_at_ts=datetime.now(timezone.utc).timestamp(),
                        )
            except Exception as e:
                logger.warning("[ReportScheduler] tick failed: %s", e)
            await asyncio.sleep(30.0)
