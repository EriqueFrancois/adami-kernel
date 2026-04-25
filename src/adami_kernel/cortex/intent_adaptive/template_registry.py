# src/adami_kernel/cortex/intent_adaptive/template_registry.py
"""Pluggable preset handlers keyed by ``intent_type`` wire ids (strategy + registry)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple

from adami_kernel.cortex.intent_adaptive.models import IntentClassificationResult
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome


class SendReplyFn(Protocol):
    """Narrow port for ``DecisionProcessor`` / kernel reply (avoids importing the kernel)."""

    async def __call__(self, chat_id: str, text: str, platform: str) -> None: ...


class RouterCallLlmFn(Protocol):
    """Optional ``HybridLLMRouter.call_llm``-shaped hook (text in → text out)."""

    async def __call__(self, prompt: str) -> str: ...


class WebSearchFn(Protocol):
    """Optional toolbox web search hook (signature kept loose until wired)."""

    async def __call__(self, *args: object, **kwargs: object) -> object: ...


@dataclass(slots=True)
class TemplateExecutionContext:
    """Inputs and dependency ports for ``IntentTemplateHandler.execute``."""

    task_text: str
    chat_id: str
    platform: str
    trace_id: str
    send_reply: Optional[SendReplyFn] = None
    router_call_llm: Optional[RouterCallLlmFn] = None
    web_search: Optional[WebSearchFn] = None
    # Step 6: winning classification (slots, primary_type) for preset template bodies.
    classification: Optional[IntentClassificationResult] = None


class IntentTemplateHandler(Protocol):
    """Preset template: score fit against a classification, then execute with context."""

    async def match_score(self, classification: IntentClassificationResult) -> float:
        """Return > ``min_match_score`` on the registry to be eligible; higher wins."""

    async def execute(self, context: TemplateExecutionContext) -> TemplateOutcome:
        """Produce user-visible Markdown and telemetry; may request Planner handoff."""


class NoOpTemplateHandler:
    """Placeholder handler (never wins ``resolve`` unless it is the only entry)."""

    async def match_score(self, classification: IntentClassificationResult) -> float:
        return 0.0

    async def execute(self, context: TemplateExecutionContext) -> TemplateOutcome:
        return TemplateOutcome(
            reply_markdown="",
            telemetry={"intent_template": "no_op", "trace_id": context.trace_id},
            handoff_to_dynamic=True,
        )


class TemplateRegistry:
    """
    Register ``(intent_type, handler)`` pairs. ``resolve`` evaluates all handlers
    and picks the highest ``match_score`` (stable tie-break: first registered wins).
    """

    def __init__(self, *, min_match_score: float = 0.0) -> None:
        self._min_match_score = float(min_match_score)
        self._entries: List[Tuple[str, IntentTemplateHandler]] = []

    def register(self, intent_type: str, handler: IntentTemplateHandler) -> None:
        """Associate a handler with a wire ``intent_type`` id (observability + future filters)."""
        if not intent_type or not intent_type.strip():
            raise ValueError("intent_type must be non-empty")
        self._entries.append((intent_type.strip(), handler))

    def registered_pairs(self) -> Tuple[Tuple[str, IntentTemplateHandler], ...]:
        """Snapshot for tests / diagnostics."""
        return tuple(self._entries)

    async def resolve(
        self, classification: IntentClassificationResult
    ) -> Optional[IntentTemplateHandler]:
        """
        Return the winning handler, or ``None`` if no ``match_score`` is strictly greater
        than the current best (including when all scores are ``<= min_match_score``).
        """
        best: Optional[IntentTemplateHandler] = None
        best_score = self._min_match_score
        for _itype, handler in self._entries:
            score = float(await handler.match_score(classification))
            if score > best_score:
                best_score = score
                best = handler
        return best
