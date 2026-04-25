"""EventBus 轨迹导出：中间件 + 系统事件旁路；异步队列批量写 NDJSON，并可选转发到 Sim Webhook。"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, List, Optional

import httpx

import adami_kernel.config as config_mod
from adami_kernel.integration.sim.schema import ReplayTraceRecordV1
from adami_kernel.integration.sim.webhook_client import post_sim_trace_webhook
from adami_kernel.telemetry.experience_sink import experience_episode_id_ctx, redact_payload

logger = logging.getLogger("AdamI-SimTraceSink")

_sink: Optional["EventBusTraceSink"] = None


async def reset_sim_trace_sink_for_tests() -> None:
    """测试隔离：停止 worker 并丢弃单例。"""
    global _sink
    if _sink is not None:
        await _sink.stop()
    _sink = None


def get_trace_sink() -> "EventBusTraceSink":
    global _sink
    if _sink is None:
        _sink = EventBusTraceSink()
    return _sink


def event_to_record(event: Any) -> ReplayTraceRecordV1:
    payload = getattr(event, "payload", None) or {}
    if not isinstance(payload, dict):
        payload = {"_non_dict_payload": str(payload)[:2000]}
    ep_token = experience_episode_id_ctx.get(None)
    episode_id = str(ep_token) if ep_token is not None else None
    redacted = redact_payload(dict(payload))
    phase: Optional[str] = None
    checkpoint_seq: Optional[int] = None
    et = redacted.get("event_type") if isinstance(redacted, dict) else None
    if et == "PHASE_TRANSITION":
        phase = redacted.get("phase") or redacted.get("to_phase")
        if phase is not None:
            phase = str(phase)
        raw_cs = redacted.get("checkpoint_seq")
        if raw_cs is not None:
            try:
                checkpoint_seq = int(raw_cs)
            except (TypeError, ValueError):
                checkpoint_seq = None
    return ReplayTraceRecordV1(
        ts=time.time(),
        trace_id=str(getattr(event, "trace_id", "") or ""),
        episode_id=episode_id,
        source_module=str(getattr(event, "source_module", "") or ""),
        target_topic=str(getattr(event, "target_topic", "") or ""),
        event_type="adami_event",
        payload_redacted=redacted,
        phase=phase,
        checkpoint_seq=checkpoint_seq,
    )


def _export_path() -> Path:
    s = config_mod.settings
    raw = getattr(s, "ADAMI_SIM_TRACE_EXPORT_PATH", None)
    if raw and str(raw).strip():
        return Path(str(raw)).expanduser()
    return s.adami_data_dir_path / "traces" / "eventbus.ndjson"


def _topic_allowed(topic: str) -> bool:
    allow = getattr(config_mod.settings, "ADAMI_SIM_TRACE_TOPICS_ALLOWLIST", None) or []
    if not allow:
        return True
    return topic in allow


class EventBusTraceSink:
    """队列 + 后台 flush；关闭导出时 ``offer`` 为 O(1) 布尔判断。"""

    def __init__(self) -> None:
        self._q: Optional[asyncio.Queue[ReplayTraceRecordV1]] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._http: Optional[httpx.AsyncClient] = None

    def _enabled(self) -> bool:
        return config_mod.sim_module_master_enabled(config_mod.settings) and bool(
            getattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)
        )

    async def start(self) -> None:
        if not self._enabled():
            return
        if self._task is not None and not self._task.done():
            return
        max_q = int(getattr(config_mod.settings, "ADAMI_SIM_TRACE_MAX_QUEUE", 4096) or 4096)
        self._q = asyncio.Queue(maxsize=max(64, max_q))
        self._http = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._worker_loop(), name="sim-trace-export")
        logger.info("[SimTrace] export worker started path=%s", _export_path())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._http:
            await self._http.aclose()
            self._http = None
        self._q = None

    async def middleware(self, event: Any) -> bool:
        await self.offer(event)
        return True

    async def offer(self, event: Any) -> None:
        if not self._enabled():
            return
        if self._q is None:
            return
        topic = str(getattr(event, "target_topic", "") or "")
        if not _topic_allowed(topic):
            return
        self._enqueue_drop_oldest(event_to_record(event))

    def _enqueue_drop_oldest(self, rec: ReplayTraceRecordV1) -> None:
        assert self._q is not None
        try:
            self._q.put_nowait(rec)
            return
        except asyncio.QueueFull:
            pass
        try:
            self._q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            self._q.put_nowait(rec)
        except asyncio.QueueFull:
            logger.debug("[SimTrace] queue full, dropped record trace_id=%s", rec.trace_id)

    async def _worker_loop(self) -> None:
        assert self._q is not None
        interval = float(
            getattr(config_mod.settings, "ADAMI_SIM_TRACE_FLUSH_INTERVAL_SEC", 0.25) or 0.25
        )
        batch_max = int(getattr(config_mod.settings, "ADAMI_SIM_TRACE_BATCH_SIZE", 64) or 64)
        path = _export_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            batch: List[ReplayTraceRecordV1] = []
            try:
                batch.append(await self._q.get())
                t0 = time.monotonic()
                while len(batch) < batch_max:
                    remaining = interval - (time.monotonic() - t0)
                    if remaining <= 0:
                        break
                    try:
                        batch.append(await asyncio.wait_for(self._q.get(), timeout=remaining))
                    except asyncio.TimeoutError:
                        break
                await self._flush_batch(batch, path)
            except asyncio.CancelledError:
                if batch:
                    await self._flush_batch(batch, path)
                raise
            except Exception as e:
                logger.warning("[SimTrace] worker error (continuing): %s", e)
                await asyncio.sleep(min(interval, 1.0))

    async def _flush_batch(self, batch: List[ReplayTraceRecordV1], path: Path) -> None:
        if not batch:
            return
        text = "".join([r.to_ndjson_line() for r in batch])
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            logger.warning("[SimTrace] write failed: %s", e)
            return

        if self._http:
            await post_sim_trace_webhook(self._http, batch, text)


async def offer_trace_event_for_system_path(event: Any) -> None:
    """系统事件绕过中间件时由 ``EventBus.publish`` 调用。"""
    await get_trace_sink().offer(event)
