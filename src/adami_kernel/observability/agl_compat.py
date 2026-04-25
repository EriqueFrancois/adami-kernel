"""Agent Lightning 与 AdamI 观测统一入口（阶段 5）。

- **内核进程**（默认）：若 ``ADAMI_AGL_ENABLED``，不 ``import agentlightning``（避免拖入 Trainer），
  奖励经 ``experience_sink``；span 为 noop。
- **训练进程**（``ADAMI_AGL_TRAIN_PROCESS=1``）：仅懒加载 ``emitter.reward`` 与 ``tracer.base``，
  使用 0.3 的 ``emit_reward(reward, attributes=...)`` 与 ``get_active_tracer().operation_context``。
- **全关**：noop。

``run_trainer`` 在导入 ``DecisionProcessor`` 之前设置 ``ADAMI_AGL_TRAIN_PROCESS``。
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable, Iterator, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t

logger = logging.getLogger("AdamI-AGL")


def _aglc_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


ADAMI_AGL_TRAIN_ENV = "ADAMI_AGL_TRAIN_PROCESS"

HAS_AGL_TRACE: bool = False
AGL_MODE: str = "noop"  # noop | kernel_sink | train_emitter
_agl_emit_reward: Optional[Callable[..., Any]] = None
_get_active_tracer_fn: Optional[Callable[[], Any]] = None


def is_agl_train_process() -> bool:
    return os.environ.get(ADAMI_AGL_TRAIN_ENV) == "1"


def should_record_agl_reward() -> bool:
    """训练进程或「内核开 AGL 且未开经验池」时走 AGL 侧奖励语义。"""
    from adami_kernel.config import settings

    if is_agl_train_process():
        return True
    return bool(settings.ADAMI_AGL_ENABLED and not settings.ADAMI_EXPERIENCE_ENABLED)


class DummyAgl:
    """与历史 DummyAgl 行为一致的安全桩。"""

    @contextmanager
    def trace(
        self,
        trace_id: str | None = None,
        task_description: str | None = None,
        metadata: dict | None = None,
    ):
        logger.debug(_aglc_t("aglc.debug.noop_trace_start", tid=trace_id or "unknown"))
        try:
            tid = trace_id or f"noop_{int(time.time() * 1000)}"
            yield type("DummySpan", (), {"trace_id": tid})()
        finally:
            logger.debug(_aglc_t("aglc.debug.noop_trace_end", tid=trace_id or "unknown"))

    def emit_reward(
        self,
        trace_id: str | None = None,
        reward: float = 0.0,
        metadata: dict | None = None,
    ):
        logger.debug(_aglc_t("aglc.debug.noop_reward", rw=reward))


class NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, *args: object):
        pass

    def set_attribute(self, *args: Any, **kwargs: Any):
        pass


class NoopTracer:
    def start_as_current_span(self, *args: Any, **kwargs: Any):
        return NoopSpan()

    def emit_reward(self, *args: Any, **kwargs: Any):
        pass


class _NoopDecisionTracer:
    def start_as_current_span(self, *args: Any, **kwargs: Any):
        return NoopTracer().start_as_current_span()

    def emit_reward(self, *args: Any, **kwargs: Any) -> None:
        return None


class KernelSinkAgl:
    """内核：奖励写入经验池。"""

    @contextmanager
    def trace(
        self,
        trace_id: str | None = None,
        task_description: str | None = None,
        metadata: dict | None = None,
    ):
        with DummyAgl().trace(trace_id, task_description, metadata) as span:
            yield span

    def emit_reward(
        self,
        trace_id: str | None = None,
        reward: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        from adami_kernel.telemetry.experience_sink import get_experience_sink

        get_experience_sink().record_feedback(
            trace_id=str(trace_id or "kernel"),
            reward=float(reward),
            metadata=dict(metadata or {}),
            source="agl_compat.kernel_sink",
        )


class TrainEmitterAgl:
    """训练进程：0.3 ``emit_reward``。"""

    def __init__(self, emit_fn: Callable[..., Any]) -> None:
        self._emit = emit_fn

    @contextmanager
    def trace(
        self,
        trace_id: str | None = None,
        task_description: str | None = None,
        metadata: dict | None = None,
    ):
        with DummyAgl().trace(trace_id, task_description, metadata) as span:
            yield span

    def emit_reward(
        self,
        trace_id: str | None = None,
        reward: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        attrs: dict[str, Any] = dict(metadata or {})
        if trace_id is not None:
            attrs.setdefault("adami.trace_id", str(trace_id))
        try:
            self._emit(float(reward), attributes=attrs or None)
        except Exception as exc:
            logger.debug(_aglc_t("aglc.debug.train_emit_fail", e=exc))


class KernelSinkDecisionTracer:
    """内核：span noop；经验池开启时由 ``decision_processor._decision_reward`` / router 负责 sink，此处跳过。"""

    def start_as_current_span(
        self,
        name: str,
        trace_id: Any = None,
        task_description: Any = None,
        metadata: Any = None,
        **kwargs: Any,
    ):
        _ = name, trace_id, task_description, metadata, kwargs
        return NoopTracer().start_as_current_span()

    def emit_reward(
        self, trace_id: Any = None, reward: float = 0.0, metadata: Any = None, **kwargs: Any
    ) -> None:
        _ = kwargs
        from adami_kernel.config import settings

        if settings.ADAMI_EXPERIENCE_ENABLED:
            return
        KernelSinkAgl().emit_reward(trace_id=trace_id, reward=reward, metadata=dict(metadata or {}))


class TrainDecisionTracer:
    """训练：``operation_context`` + 0.3 ``emit_reward``。"""

    def __init__(
        self,
        emit_fn: Callable[..., Any],
        get_tracer: Callable[[], Any],
    ) -> None:
        self._emit = emit_fn
        self._get_tracer = get_tracer

    def start_as_current_span(
        self,
        name: str,
        trace_id: Any = None,
        task_description: Any = None,
        metadata: Any = None,
        **kwargs: Any,
    ):
        _ = kwargs
        tr = self._get_tracer()
        if tr is None:
            return NoopTracer().start_as_current_span()
        attrs: dict[str, Any] = dict(metadata or {})
        if trace_id is not None:
            attrs["adami.trace_id"] = str(trace_id)
        if task_description is not None:
            attrs["adami.task_description"] = str(task_description)
        return tr.operation_context(name, attributes=attrs or None)

    def emit_reward(
        self, trace_id: Any = None, reward: float = 0.0, metadata: Any = None, **kwargs: Any
    ) -> None:
        _ = kwargs
        from adami_kernel.config import settings

        if settings.ADAMI_EXPERIENCE_ENABLED:
            return
        attrs: dict[str, Any] = dict(metadata or {})
        if trace_id is not None:
            attrs.setdefault("adami.trace_id", str(trace_id))
        try:
            self._emit(float(reward), attributes=attrs or None)
        except Exception as exc:
            logger.debug(_aglc_t("aglc.debug.train_dt_emit_fail", e=exc))


def _init_agl() -> None:
    global HAS_AGL_TRACE, AGL_MODE, _agl_emit_reward, _get_active_tracer_fn, agl, decision_tracer

    from adami_kernel.config import settings

    if is_agl_train_process():
        try:
            from agentlightning.emitter.reward import emit_reward as _er
            from agentlightning.tracer.base import get_active_tracer as _gat

            _agl_emit_reward = _er
            _get_active_tracer_fn = _gat
            AGL_MODE = "train_emitter"
            HAS_AGL_TRACE = False
            agl = TrainEmitterAgl(_er)
            decision_tracer = TrainDecisionTracer(_er, _gat)
            logger.info(_aglc_t("aglc.log.train_ready"))
            return
        except Exception as exc:
            logger.warning(_aglc_t("aglc.warn.train_fallback", e=exc))

    if settings.ADAMI_AGL_ENABLED:
        AGL_MODE = "kernel_sink"
        HAS_AGL_TRACE = False
        _agl_emit_reward = None
        _get_active_tracer_fn = None
        agl = KernelSinkAgl()
        decision_tracer = KernelSinkDecisionTracer()
        logger.info(_aglc_t("aglc.log.kernel_sink"))
        return

    AGL_MODE = "noop"
    HAS_AGL_TRACE = False
    _agl_emit_reward = None
    _get_active_tracer_fn = None
    agl = DummyAgl()
    decision_tracer = _NoopDecisionTracer()


agl: Any = DummyAgl()
decision_tracer: Any = _NoopDecisionTracer()
_init_agl()


@contextmanager
def get_trace_context(
    trace_id: str | None = None,
    task_description: str | None = None,
    metadata: dict | None = None,
) -> Iterator[Any]:
    """HybridLLMRouter / SkillComposer / ReflexionLoop 共用的 trace 入口。"""
    if AGL_MODE == "train_emitter" and _get_active_tracer_fn is not None:
        tr = _get_active_tracer_fn()
        if tr is not None:
            tid = trace_id or f"adami_{int(time.time() * 1000)}"
            attrs: dict[str, Any] = dict(metadata or {})
            attrs["adami.trace_id"] = tid
            if task_description:
                attrs["adami.task_description"] = task_description
            span_name = (
                (str(task_description)[:120] if task_description else None)
                or tid[:80]
                or "adami.trace"
            )
            with tr.operation_context(span_name, attributes=attrs):
                yield type("AdamiTrace", (), {"trace_id": tid})()
            return
    if AGL_MODE == "kernel_sink":
        with KernelSinkAgl().trace(trace_id, task_description, metadata) as span:
            yield span
        return
    with DummyAgl().trace(trace_id, task_description, metadata) as span:
        yield span


def train_rollout_trace_cm(tracer: Any, *, rollout_id: str, attempt_id: str | None):
    """``adami_agl_agent``：``trace_context(rollout_id=, attempt_id=)``；不支持时返回空异步上下文。"""
    try:
        if attempt_id is not None:
            return tracer.trace_context(
                name="adami_kernel.decision_rollout",
                rollout_id=str(rollout_id),
                attempt_id=str(attempt_id),
            )
        return tracer.trace_context(name="adami_kernel.decision_rollout")
    except NotImplementedError:
        return _async_null_cm()
    except Exception as exc:
        logger.debug(_aglc_t("aglc.debug.trace_ctx_downgrade", e=exc))
        return _async_null_cm()


@asynccontextmanager
async def _async_null_cm():
    yield None
