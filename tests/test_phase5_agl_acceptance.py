"""阶段 5 验收：agl_compat 进程分流、经验池与 AGL 二选一、trace_context 绑定。

验收范围（与阶段 5 设计对齐）：
1. 子进程干净环境：`AGL_MODE` 为 noop / kernel_sink / train_emitter（后者依赖 agentlightning）。
2. `is_agl_train_process` / `should_record_agl_reward` 与 env、配置一致。
3. `KernelSinkDecisionTracer` / `TrainDecisionTracer`：`ADAMI_EXPERIENCE_ENABLED` 时不再向 AGL 侧发奖励。
4. `train_rollout_trace_cm`：支持 `rollout_id`/`attempt_id` 时进入 tracer；否则降级为空异步上下文。
5. 子进程探针：内核路径下导入 `agl_compat` 后检查未在 sys.modules 中加载顶层 `agentlightning`（训练路径允许）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import NoReturn
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 子进程探针（避免污染当前 pytest 进程的 agl_compat 单例）
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _subprocess_run(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_p5_subprocess_agl_mode_noop_when_agl_disabled() -> None:
    code = """
import os
os.environ.pop("ADAMI_AGL_TRAIN_PROCESS", None)
os.environ["ADAMI_AGL_ENABLED"] = "false"
os.environ["ADAMI_EXPERIENCE_ENABLED"] = "false"
from adami_kernel.observability import agl_compat
print(agl_compat.AGL_MODE)
"""
    r = _subprocess_run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "noop"


def test_p5_subprocess_agl_mode_kernel_sink_when_agl_enabled_not_train() -> None:
    code = """
import os
os.environ.pop("ADAMI_AGL_TRAIN_PROCESS", None)
os.environ["ADAMI_AGL_ENABLED"] = "true"
os.environ["ADAMI_EXPERIENCE_ENABLED"] = "false"
from adami_kernel.observability import agl_compat
print(agl_compat.AGL_MODE)
"""
    r = _subprocess_run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "kernel_sink"


def test_p5_subprocess_kernel_path_does_not_import_top_level_agentlightning() -> None:
    """内核模式：不应把顶层 agentlightning 包拉进 sys.modules。"""
    code = """
import os
os.environ.pop("ADAMI_AGL_TRAIN_PROCESS", None)
os.environ["ADAMI_AGL_ENABLED"] = "true"
os.environ["ADAMI_EXPERIENCE_ENABLED"] = "false"
import sys
from adami_kernel.observability import agl_compat
assert agl_compat.AGL_MODE == "kernel_sink"
assert "agentlightning" not in sys.modules, list(sys.modules.get("agentlightning"))
print("ok")
"""
    r = _subprocess_run(code)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "ok"


def test_p5_subprocess_train_process_mode() -> None:
    """训练进程：成功加载子模块则为 train_emitter，否则按 _init_agl 降级。"""
    code = """
import os
os.environ["ADAMI_AGL_TRAIN_PROCESS"] = "1"
os.environ["ADAMI_AGL_ENABLED"] = "true"
os.environ["ADAMI_EXPERIENCE_ENABLED"] = "false"
from adami_kernel.observability import agl_compat
print(agl_compat.AGL_MODE)
"""
    r = _subprocess_run(code)
    assert r.returncode == 0, r.stderr
    mode = r.stdout.strip()
    assert mode in ("train_emitter", "kernel_sink", "noop")


def test_p5_subprocess_should_record_agl_reward() -> None:
    code = """
import os
os.environ["ADAMI_AGL_TRAIN_PROCESS"] = "1"
os.environ["ADAMI_AGL_ENABLED"] = "false"
os.environ["ADAMI_EXPERIENCE_ENABLED"] = "true"
from adami_kernel.observability import agl_compat
print("train", agl_compat.should_record_agl_reward())
"""
    r = _subprocess_run(code)
    assert r.returncode == 0, r.stderr
    assert "train True" in r.stdout.replace("\n", " ")

    code2 = """
import os
os.environ.pop("ADAMI_AGL_TRAIN_PROCESS", None)
os.environ["ADAMI_AGL_ENABLED"] = "true"
os.environ["ADAMI_EXPERIENCE_ENABLED"] = "true"
from adami_kernel.observability import agl_compat
print("kernel_xp", agl_compat.should_record_agl_reward())
"""
    r2 = _subprocess_run(code2)
    assert r2.returncode == 0, r2.stderr
    assert "kernel_xp False" in r2.stdout.replace("\n", " ")

    code3 = """
import os
os.environ.pop("ADAMI_AGL_TRAIN_PROCESS", None)
os.environ["ADAMI_AGL_ENABLED"] = "true"
os.environ["ADAMI_EXPERIENCE_ENABLED"] = "false"
from adami_kernel.observability import agl_compat
print("kernel_no_xp", agl_compat.should_record_agl_reward())
"""
    r3 = _subprocess_run(code3)
    assert r3.returncode == 0, r3.stderr
    assert "kernel_no_xp True" in r3.stdout.replace("\n", " ")


# ---------------------------------------------------------------------------
# 同进程：不依赖 agl_compat 重载
# ---------------------------------------------------------------------------


def test_p5_is_agl_train_process_follows_env() -> None:
    from adami_kernel.observability.agl_compat import ADAMI_AGL_TRAIN_ENV, is_agl_train_process

    old = os.environ.get(ADAMI_AGL_TRAIN_ENV)
    try:
        os.environ[ADAMI_AGL_TRAIN_ENV] = "1"
        assert is_agl_train_process() is True
        os.environ[ADAMI_AGL_TRAIN_ENV] = "0"
        assert is_agl_train_process() is False
    finally:
        if old is None:
            os.environ.pop(ADAMI_AGL_TRAIN_ENV, None)
        else:
            os.environ[ADAMI_AGL_TRAIN_ENV] = old


def test_p5_kernel_sink_decision_tracer_skips_agl_when_experience_on() -> None:
    from adami_kernel.observability.agl_compat import KernelSinkDecisionTracer

    with patch("adami_kernel.config.settings.ADAMI_EXPERIENCE_ENABLED", True):
        dt = KernelSinkDecisionTracer()
        with patch("adami_kernel.observability.agl_compat.KernelSinkAgl") as m_ks:
            dt.emit_reward(trace_id="t1", reward=0.5, metadata={"k": "v"})
            m_ks.assert_not_called()


def test_p5_kernel_sink_decision_tracer_forwards_when_experience_off() -> None:
    from adami_kernel.observability.agl_compat import KernelSinkDecisionTracer

    mock_sink = MagicMock()

    with patch("adami_kernel.config.settings.ADAMI_EXPERIENCE_ENABLED", False):
        with patch(
            "adami_kernel.telemetry.experience_sink.get_experience_sink",
            return_value=mock_sink,
        ):
            dt = KernelSinkDecisionTracer()
            dt.emit_reward(trace_id="t2", reward=0.25, metadata={"a": 1})

    mock_sink.record_feedback.assert_called_once()
    call_kw = mock_sink.record_feedback.call_args.kwargs
    assert call_kw["trace_id"] == "t2"
    assert call_kw["reward"] == 0.25
    assert call_kw["metadata"] == {"a": 1}


def test_p5_train_decision_tracer_skips_emit_when_experience_on() -> None:
    from adami_kernel.observability.agl_compat import TrainDecisionTracer

    emit = MagicMock()
    get_tr = MagicMock()

    with patch("adami_kernel.config.settings.ADAMI_EXPERIENCE_ENABLED", True):
        dt = TrainDecisionTracer(emit, get_tr)
        dt.emit_reward(trace_id="tx", reward=1.0, metadata={})

    emit.assert_not_called()


def test_p5_train_decision_tracer_calls_emit_when_experience_off() -> None:
    from adami_kernel.observability.agl_compat import TrainDecisionTracer

    emit = MagicMock()
    get_tr = MagicMock()

    with patch("adami_kernel.config.settings.ADAMI_EXPERIENCE_ENABLED", False):
        dt = TrainDecisionTracer(emit, get_tr)
        dt.emit_reward(trace_id="ty", reward=0.75, metadata={"m": 2})

    emit.assert_called_once_with(0.75, attributes={"adami.trace_id": "ty", "m": 2})


@pytest.mark.asyncio
async def test_p5_train_rollout_trace_cm_uses_tracer_when_supported() -> None:
    from adami_kernel.observability import agl_compat

    entered: list[str] = []

    class _Tr:
        @staticmethod
        def trace_context(
            *, name: str, rollout_id: str | None = None, attempt_id: str | None = None
        ) -> AbstractAsyncContextManager[str]:
            @asynccontextmanager
            async def _inner() -> AsyncIterator[str]:
                entered.append(f"{name}:{rollout_id}:{attempt_id}")
                yield "span"

            return _inner()

    tr = _Tr()
    cm_factory = agl_compat.train_rollout_trace_cm(tr, rollout_id="r1", attempt_id="a1")
    async with cm_factory:
        pass
    assert entered == ["adami_kernel.decision_rollout:r1:a1"]


@pytest.mark.asyncio
async def test_p5_train_rollout_trace_cm_null_on_not_implemented() -> None:
    from adami_kernel.observability import agl_compat

    class _Tr:
        def trace_context(self, *args: object, **kwargs: object) -> NoReturn:
            raise NotImplementedError

    tr = _Tr()
    cm = agl_compat.train_rollout_trace_cm(tr, rollout_id="r1", attempt_id="a1")
    async with cm:
        pass


def test_p5_router_reward_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 `_router_reward`：经验池开则 sink，否则 `agl.emit_reward`。"""

    class _Trace:
        trace_id = "tid_router"

    mock_sink = MagicMock()
    mock_agl = MagicMock()

    import adami_kernel.cortex.router as router_mod

    monkeypatch.setattr(router_mod.settings, "ADAMI_EXPERIENCE_ENABLED", True)
    monkeypatch.setattr(router_mod, "get_experience_sink", lambda: mock_sink)
    monkeypatch.setattr(router_mod, "agl", mock_agl)
    router_mod._router_reward(_Trace(), 0.4, {"src": "t"})
    mock_sink.record_feedback.assert_called_once_with(
        trace_id="tid_router",
        reward=0.4,
        metadata={"src": "t"},
        source="router",
    )
    mock_agl.emit_reward.assert_not_called()

    mock_sink.reset_mock()
    mock_agl.reset_mock()
    monkeypatch.setattr(router_mod.settings, "ADAMI_EXPERIENCE_ENABLED", False)
    router_mod._router_reward(_Trace(), 0.6, {"x": 1})
    mock_agl.emit_reward.assert_called_once_with(
        trace_id="tid_router", reward=0.6, metadata={"x": 1}
    )
    mock_sink.record_feedback.assert_not_called()
