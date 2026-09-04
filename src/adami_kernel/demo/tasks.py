"""Task registry, slot/queue orchestration, disconnect grace, terminal ring."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from adami_kernel.demo.config import DemoSettings
from adami_kernel.demo.executor import execute_turn
from adami_kernel.demo.fallback import canned_fallback
from adami_kernel.demo.limits import RateLimiter
from adami_kernel.demo.llm.fake import FakeLLM
from adami_kernel.demo.llm.openai_compatible import OpenAICompatibleLLM
from adami_kernel.demo.messages import error_message
from adami_kernel.demo.metrics import DemoMetrics
from adami_kernel.demo.queue import Waiter, WaitQueue
from adami_kernel.demo.redact import redact_text, safe_error_message
from adami_kernel.demo.security import new_csrf_token, new_session_id, new_task_id
from adami_kernel.demo.sessions import DemoSession, SessionStore
from adami_kernel.demo.sse import format_sse

logger = logging.getLogger("adami-demo")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class DemoTask:
    task_id: str
    session_id: str
    scenario_id: str
    message: str
    locale: str
    mode: str
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    slot_held: bool = False
    queue_held: bool = False
    released: str | None = None
    terminal_sent: bool = False
    ring: bytearray = field(default_factory=bytearray)
    subscribers: list[asyncio.Queue[bytes | None]] = field(default_factory=list)
    disconnect_at: float | None = None
    grace_handle: asyncio.TimerHandle | None = None
    worker: asyncio.Task[None] | None = None
    created_at: float = field(default_factory=time.time)
    terminal_at: float | None = None
    live_connections: int = 0


class DemoRuntime:
    def __init__(self, settings: DemoSettings, llm: Any | None = None) -> None:
        self.settings = settings
        self.sessions = SessionStore(
            idle_ttl=settings.SESSION_IDLE_TTL_SEC,
            max_ttl=settings.SESSION_MAX_TTL_SEC,
        )
        self.limits = RateLimiter(
            ip_per_minute=settings.RATE_IP_PER_MINUTE,
            ip_per_day=settings.RATE_IP_PER_DAY,
            session_per_minute=settings.RATE_SESSION_PER_MINUTE,
        )
        self.metrics = DemoMetrics()
        self.wait_queue = WaitQueue(settings.QUEUE_MAX)
        self.tasks: dict[str, DemoTask] = {}
        self._lock = asyncio.Lock()
        self._running = 0
        self._closing = False
        self._purge_task: asyncio.Task[None] | None = None
        if llm is not None:
            self.llm = llm
        elif settings.effective_provider() == "openai_compatible":
            self.llm = OpenAICompatibleLLM(
                base_url=settings.LLM_BASE_URL,
                model=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                allow_http=settings.LLM_ALLOW_HTTP,
                allowed_hosts=settings.llm_allowed_host_list() or None,
            )
        else:
            self.llm = FakeLLM()

    async def startup(self) -> None:
        self._purge_task = asyncio.create_task(self._purge_loop())

    async def shutdown(self) -> None:
        self._closing = True
        if self._purge_task:
            self._purge_task.cancel()
            try:
                await self._purge_task
            except asyncio.CancelledError:
                pass
        for task in list(self.tasks.values()):
            task.cancel.set()

    async def _purge_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(max(0.05, float(self.settings.SESSION_CLEANUP_SEC)))
                self.sessions.purge_expired()
                now = time.time()
                for tid, task in list(self.tasks.items()):
                    if task.terminal_at and now - task.terminal_at > self.settings.TERMINAL_RETAIN_SEC:
                        if task.live_connections <= 0:
                            self.tasks.pop(tid, None)
        except asyncio.CancelledError:
            return

    def create_session(self, locale: str) -> tuple[DemoSession, str]:
        now = time.time()
        sid = new_session_id()
        sess = DemoSession(
            session_id=sid,
            locale=locale,
            csrf_token=new_csrf_token(),
            created_at=now,
            last_seen_at=now,
        )
        self.sessions.put(sess)
        return sess, _iso(sess.expires_at(self.sessions.idle_ttl, self.sessions.max_ttl))

    def get_session(self, session_id: str | None) -> DemoSession | None:
        sess = self.sessions.get(session_id)
        if sess is None:
            return None
        if sess.is_expired(time.time(), self.sessions.idle_ttl, self.sessions.max_ttl):
            self.sessions.drop(sess.session_id)
            return None
        sess.touch(time.time())
        return sess

    def _append_ring(self, task: DemoTask, chunk: bytes) -> None:
        task.ring.extend(chunk)
        overflow = len(task.ring) - int(self.settings.RING_MAX_BYTES)
        if overflow > 0:
            del task.ring[:overflow]

    def _publish(self, task: DemoTask, event: str, payload: dict[str, Any]) -> None:
        raw = format_sse(event, payload)
        self._append_ring(task, raw)
        for q in list(task.subscribers):
            try:
                q.put_nowait(raw)
            except asyncio.QueueFull:
                pass

    def subscribe(self, task: DemoTask) -> asyncio.Queue[bytes | None]:
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        if task.ring:
            try:
                q.put_nowait(bytes(task.ring))
            except asyncio.QueueFull:
                pass
        task.subscribers.append(q)
        task.live_connections += 1
        if task.grace_handle is not None:
            task.grace_handle.cancel()
            task.grace_handle = None
            task.disconnect_at = None
        return q

    def unsubscribe(self, task: DemoTask, q: asyncio.Queue[bytes | None], loop: asyncio.AbstractEventLoop) -> None:
        if q in task.subscribers:
            task.subscribers.remove(q)
        task.live_connections = max(0, task.live_connections - 1)
        if task.live_connections <= 0 and not task.finished.is_set():
            task.disconnect_at = time.time()

            def _fire() -> None:
                if task.live_connections <= 0 and not task.finished.is_set():
                    loop.create_task(self._cancel_task(task, from_disconnect=True))

            task.grace_handle = loop.call_later(self.settings.DISCONNECT_GRACE_SEC, _fire)

    async def _try_take_slot(self, task: DemoTask) -> bool:
        async with self._lock:
            if self._running < self.settings.GLOBAL_SLOTS:
                self._running += 1
                task.slot_held = True
                return True
            return False

    async def _release_slot_or_transfer(self, task: DemoTask) -> None:
        async with self._lock:
            if not task.slot_held:
                return
            task.slot_held = False
            waiter = self.wait_queue.pop_next()
            while waiter is not None and waiter.cancelled.is_set():
                waiter = self.wait_queue.pop_next()
            if waiter is not None:
                nxt = self.tasks.get(waiter.task_id)
                if nxt is not None:
                    nxt.queue_held = False
                    nxt.slot_held = True
                    waiter.claimed.set()
                    return
            self._running = max(0, self._running - 1)

    async def _cancel_task(self, task: DemoTask, *, from_disconnect: bool = False) -> None:
        if task.finished.is_set():
            return
        task.cancel.set()
        if task.queue_held:
            async with self._lock:
                w = self.wait_queue.remove(task.task_id)
                if w is not None:
                    w.cancelled.set()
                    w.claimed.set()
                task.queue_held = False
            if not task.terminal_sent:
                task.released = "queue"
                self._finish_with(
                    task,
                    [
                        ("cancelled", {"taskId": task.task_id, "released": "queue"}),
                    ],
                )
            return
        task.released = "slot"
        if task.worker is not None and not task.worker.done():
            task.worker.cancel()

    def _finish_with(self, task: DemoTask, events: list[tuple[str, dict[str, Any]]]) -> None:
        if task.terminal_sent:
            return
        for ev, payload in events:
            self._publish(task, ev, payload)
        task.terminal_sent = True
        task.terminal_at = time.time()
        task.finished.set()
        sess = self.sessions.get(task.session_id)
        if sess is not None and sess.busy_task_id == task.task_id:
            sess.busy_task_id = None
        for q in list(task.subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def start_turn(self, session: DemoSession, scenario_id: str, message: str) -> DemoTask:
        if self._closing:
            raise RuntimeError("unavailable")
        task = DemoTask(
            task_id=new_task_id(),
            session_id=session.session_id,
            scenario_id=scenario_id,
            message=message,
            locale=session.locale,
            mode=self.settings.accepted_mode(),
        )
        self.tasks[task.task_id] = task
        session.busy_task_id = task.task_id
        got = await self._try_take_slot(task)
        if got:
            task.worker = asyncio.create_task(self._run_worker(task, session, queued=False))
            return task
        waiter = Waiter(task_id=task.task_id, session_id=session.session_id, enqueued_at=time.time())
        pos = self.wait_queue.try_enqueue(waiter)
        if pos is None:
            session.busy_task_id = None
            fb = canned_fallback(session.locale, scenario_id, "queue_full")
            self._finish_with(
                task,
                [
                    (
                        "error",
                        {
                            "code": "queue_full",
                            "message": error_message(session.locale, "queue_full"),
                        },
                    ),
                    ("fallback", fb.model_dump()),
                ],
            )
            self.metrics.errors += 1
            return task
        task.queue_held = True
        self._publish(
            task,
            "queued",
            {
                "taskId": task.task_id,
                "position": pos,
                "queueLength": len(self.wait_queue),
                "etaSec": int(self.settings.WAIT_TIMEOUT_SEC * pos / max(1, self.settings.GLOBAL_SLOTS)),
            },
        )
        task.worker = asyncio.create_task(
            self._wait_then_run(task, session, waiter),
        )
        return task

    async def _wait_then_run(self, task: DemoTask, session: DemoSession, waiter: Waiter) -> None:
        try:
            await asyncio.wait_for(waiter.claimed.wait(), timeout=self.settings.WAIT_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            async with self._lock:
                self.wait_queue.remove(task.task_id)
                task.queue_held = False
            fb = canned_fallback(session.locale, task.scenario_id, "wait_timeout")
            self._finish_with(
                task,
                [
                    (
                        "error",
                        {
                            "code": "wait_timeout",
                            "message": error_message(session.locale, "wait_timeout"),
                        },
                    ),
                    ("fallback", fb.model_dump()),
                ],
            )
            self.metrics.errors += 1
            return
        if waiter.cancelled.is_set() or task.cancel.is_set():
            return
        await self._run_worker(task, session, queued=True)

    async def _stream_execute(self, task: DemoTask, session: DemoSession) -> dict[str, Any] | None:
        fb_needed: dict[str, Any] | None = None
        async for ev, payload in execute_turn(
            llm=self.llm,
            session=session,
            scenario_id=task.scenario_id,
            message=task.message,
            max_tokens=self.settings.LLM_MAX_OUTPUT_TOKENS,
            timeout_sec=self.settings.LLM_TIMEOUT_SEC,
            cancel_event=task.cancel,
            max_prompt_chars=self.settings.LLM_MAX_PROMPT_CHARS,
        ):
            if ev == "assistant_text":
                self.metrics.llm_calls += 1
                self.metrics.estimated_output_tokens += max(
                    1, len(str(payload.get("text") or "")) // 4
                )
                continue
            if ev == "error":
                code = str(payload.get("code") or "unavailable")
                reason = "tool_denied" if code == "tool_denied" else "model_failed"
                fb_needed = canned_fallback(session.locale, task.scenario_id, reason).model_dump()
                self._publish(task, ev, payload)
                self.metrics.errors += 1
                continue
            self._publish(task, ev, payload)
            if task.cancel.is_set():
                break
        return fb_needed

    async def _run_worker(self, task: DemoTask, session: DemoSession, *, queued: bool) -> None:
        t0 = time.time()
        try:
            if task.finished.is_set() or task.cancel.is_set():
                return
            session.turns_used += 1
            self._publish(
                task,
                "accepted",
                {
                    "taskId": task.task_id,
                    "scenarioId": task.scenario_id,
                    "mode": task.mode,
                    "streaming": "chunked-complete",
                },
            )
            fb_needed: dict[str, Any] | None = None
            try:
                fb_needed = await asyncio.wait_for(
                    self._stream_execute(task, session),
                    timeout=self.settings.TASK_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                fb = canned_fallback(session.locale, task.scenario_id, "task_timeout")
                self._finish_with(
                    task,
                    [
                        (
                            "error",
                            {
                                "code": "unavailable",
                                "message": error_message(session.locale, "task_timeout"),
                            },
                        ),
                        ("fallback", fb.model_dump()),
                    ],
                )
                self.metrics.errors += 1
                return
            if task.cancel.is_set() and not task.terminal_sent:
                self._finish_with(
                    task,
                    [("cancelled", {"taskId": task.task_id, "released": "slot"})],
                )
                return
            if task.terminal_sent:
                return
            if fb_needed is not None:
                self._finish_with(task, [("fallback", fb_needed)])
                return
            remaining = session.turns_remaining(self.settings.MAX_TURNS)
            self._finish_with(
                task,
                [
                    (
                        "done",
                        {
                            "taskId": task.task_id,
                            "turnsRemaining": remaining,
                            "finishReason": "completed",
                        },
                    )
                ],
            )
        except asyncio.CancelledError:
            if not task.terminal_sent:
                self._finish_with(
                    task,
                    [("cancelled", {"taskId": task.task_id, "released": "slot"})],
                )
            return
        except Exception as exc:
            logger.warning("demo turn failed: %s", redact_text(safe_error_message(str(exc))))
            fb = canned_fallback(session.locale, task.scenario_id, "model_failed")
            self._finish_with(
                task,
                [
                    (
                        "error",
                        {
                            "code": "unavailable",
                            "message": error_message(session.locale, "model_failed"),
                        },
                    ),
                    ("fallback", fb.model_dump()),
                ],
            )
            self.metrics.errors += 1
        finally:
            self.metrics.record_duration(time.time() - t0)
            await self._release_slot_or_transfer(task)

    async def cancel(self, task: DemoTask) -> str:
        if task.queue_held:
            async with self._lock:
                w = self.wait_queue.remove(task.task_id)
                if w is not None:
                    w.cancelled.set()
                    w.claimed.set()
                task.queue_held = False
            self._finish_with(
                task,
                [("cancelled", {"taskId": task.task_id, "released": "queue"})],
            )
            return "queue"
        task.cancel.set()
        await self._cancel_task(task)
        return task.released or "slot"

    def health(self) -> str:
        if self._closing:
            return "unavailable"
        if self._running >= self.settings.GLOBAL_SLOTS and len(self.wait_queue) >= self.settings.QUEUE_MAX:
            return "unavailable"
        if len(self.wait_queue) > 0:
            return "degraded"
        return "ok"


async def iter_sse(runtime: DemoRuntime, task: DemoTask) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    q = runtime.subscribe(task)
    try:
        while True:
            if task.finished.is_set() and q.empty():
                break
            try:
                item = await asyncio.wait_for(q.get(), timeout=0.25)
            except asyncio.TimeoutError:
                if task.finished.is_set():
                    break
                continue
            if item is None:
                break
            yield item
    finally:
        runtime.unsubscribe(task, q, loop)
