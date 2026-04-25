"""`LitAgent` 包装：在 rollout 内调用 `DecisionProcessor.process` + 轻量 mock kernel。

训练入口禁止引用 `component_initializer`，仅以显式桩实现
[`KernelContext`][adami_kernel.core.kernel_context.KernelContext] 所要求的能力面。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Type, cast

from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.training.agl_bridge import AGL_AVAILABLE

logger = logging.getLogger("AdamI-AdamiAGLAgent")


class _StubSkillRouter:
    def is_skill_creation_task(self, task_text: str) -> bool:
        return False


class _StubIntentRouter:
    async def route_task(self, task_text: str) -> Tuple[str, Any]:
        _ = task_text
        return ("DIRECT_ANSWER", "training_stub_ok")


class _StubMemory:
    async def retrieve_recent(self, *args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        return []

    async def store_experience(self, *args: Any, **kwargs: Any) -> None:
        return None


class _StubRouter:
    async def call_llm(self, *args: Any, **kwargs: Any) -> str:
        return "THINK {}"


class _StubToolbox:
    pass


class _StubImmunity:
    async def run_with_timeout(self, coro: Any, timeout: float) -> Any:
        return await coro


class _StubEvolutionEngine:
    def get_skill(self, name: str) -> Any:
        _ = name
        return None

    async def create_new_skill(self, *args: Any, **kwargs: Any) -> Any:
        return None


class _StubPlanner:
    pass


class _StubPromptBuilder:
    system_persona: str = ""

    async def build_action_prompt(self, *args: Any, **kwargs: Any) -> str:
        return ""


class _TrainingBus:
    async def subscribe(self, topic: str) -> asyncio.Queue[AdamiEvent]:
        _ = topic
        return asyncio.Queue()

    async def publish(self, event: AdamiEvent) -> None:
        return None


class MinimalTrainingKernel:
    """`DecisionProcessor` 在 DIRECT_ANSWER 路径上所需的最小桩。"""

    def __init__(self) -> None:
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.session_locks: Dict[str, asyncio.Lock] = {}
        self.chat_locale_overrides: Dict[str, str] = {}
        self.bus = _TrainingBus()
        self.memory = _StubMemory()
        self.router = _StubRouter()
        self.toolbox = _StubToolbox()
        self.immunity = _StubImmunity()
        self.episodic_memory = None
        self.planner = _StubPlanner()
        self.intent_router = _StubIntentRouter()
        self.intent_template_registry = None
        self.skill_router = _StubSkillRouter()
        self.evolution_engine = _StubEvolutionEngine()
        self.prompt_builder = _StubPromptBuilder()
        self.skill_optimizer = None
        self.second_brain = None
        self.telegram_nerve = None
        self.discord_nerve = None
        self.proprioception = None
        self.replies: List[str] = []
        self.last_span_metadata: Dict[str, Any] = {}

    async def _send_reply(self, chat_id: Any, text: str, platform: str = "telegram") -> None:
        self.replies.append(str(text))
        _ = chat_id, platform

    async def _handle_system_action(
        self, cmd: str, current_chat_id: Optional[str], platform: str = "telegram"
    ) -> None:
        _ = cmd, current_chat_id, platform

    def _parse_decision(self, response: str) -> Tuple[str, Dict[str, Any]]:
        _ = response
        return "THINK", {}

    def _get_current_persona(self) -> str:
        return "training"


def _task_payload(task: Any) -> Dict[str, Any]:
    if isinstance(task, dict):
        return cast(Dict[str, Any], task)
    model_dump = getattr(task, "model_dump", None)
    if callable(model_dump):
        return cast(Dict[str, Any], model_dump())
    raise TypeError(f"Unsupported task type: {type(task)!r}")


def _agl_litagent_subclass() -> Type[Any]:
    from agentlightning.litagent import LitAgent
    from agentlightning.types import AttemptedRollout, NamedResources, Rollout, RolloutRawResult

    from adami_kernel.cortex.decision_processor import DecisionProcessor
    from adami_kernel.observability.agl_compat import train_rollout_trace_cm

    class _AdamiAGLLitAgent(LitAgent[Dict[str, Any]]):  # type: ignore[type-arg]
        """异步 rollout：构造 `AdamiEvent` 并 `await DecisionProcessor.process`。"""

        def is_async(self) -> bool:
            return True

        async def rollout_async(
            self,
            task: Dict[str, Any],
            resources: NamedResources,
            rollout: Rollout,
        ) -> RolloutRawResult:
            _ = resources
            data = _task_payload(task)
            kernel = MinimalTrainingKernel()
            processor = DecisionProcessor(cast(Any, kernel))
            trace_id = str(
                data.get("primary_trace_id") or data.get("episode_id") or rollout.rollout_id
            )
            chat_id = str(data.get("chat_id", "agl_train"))
            task_text = str(data.get("task", ""))
            event = AdamiEvent(
                trace_id=trace_id,
                source_module="user.prompt",
                target_topic="system.events",
                priority=EventPriority.NORMAL,
                payload={
                    "chat_id": chat_id,
                    "task": task_text,
                    "loop_depth": int(data.get("loop_depth", 0)),
                },
            )
            t0 = time.perf_counter()
            outcome = "ok"
            try:
                tr = self.get_tracer()
            except (ValueError, AttributeError):
                tr = None

            async def _run_decision() -> None:
                await processor.process(event)

            try:
                if tr is None:
                    await _run_decision()
                else:
                    attempt_id: str | None = None
                    if isinstance(rollout, AttemptedRollout):
                        attempt_id = str(rollout.attempt.attempt_id)
                    trace_cm = train_rollout_trace_cm(
                        tr, rollout_id=str(rollout.rollout_id), attempt_id=attempt_id
                    )
                    async with trace_cm:
                        await _run_decision()
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except Exception as exc:
                outcome = f"error:{type(exc).__name__}"
                logger.exception("[AdamiAGLLitAgent] DecisionProcessor.process failed: %s", exc)
            dt = time.perf_counter() - t0

            reward_hint = data.get("reward_hint")
            if reward_hint is not None:
                try:
                    reward = float(reward_hint)
                except (TypeError, ValueError):
                    reward = 1.0 if outcome == "ok" else 0.0
            else:
                reward = 1.0 if outcome == "ok" else 0.0

            kernel.last_span_metadata = {
                "adami.decision_ms": round(dt * 1000.0, 3),
                "adami.outcome": outcome,
                "adami.n_replies": len(kernel.replies),
                "adami.episode_id": data.get("episode_id"),
                "adami.rollout_id": rollout.rollout_id,
            }
            return reward

    return _AdamiAGLLitAgent


def _offline_stub_type() -> Type[Any]:
    class _AdamiAGLLitAgentOffline:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args, kwargs
            raise RuntimeError(
                "agentlightning is not installed. Install optional extra: poetry install -E training"
            )

    return _AdamiAGLLitAgentOffline


AdamiAGLLitAgent: Type[Any] = _agl_litagent_subclass() if AGL_AVAILABLE else _offline_stub_type()
