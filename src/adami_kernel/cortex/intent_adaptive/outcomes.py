# src/adami_kernel/cortex/intent_adaptive/outcomes.py
"""Structured results returned by preset intent template handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, MutableMapping


@dataclass(slots=True)
class TemplateOutcome:
    """Result of ``IntentTemplateHandler.execute`` (reply + telemetry + optional handoff)."""

    reply_markdown: str = ""
    telemetry: MutableMapping[str, Any] = field(default_factory=dict)
    handoff_to_dynamic: bool = False
