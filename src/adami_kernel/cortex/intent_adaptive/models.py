# src/adami_kernel/cortex/intent_adaptive/models.py
"""Domain contracts for tiered intent classification (Step 1: models only, no I/O)."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

# --- Intent families (behavioral space; values are stable JSON wire ids) ---


class IntentFamily(str, Enum):
    """High-level intent bucket. Extend only with versioning / migration notes."""

    SYSTEM = "system"
    RETRIEVAL = "retrieval"
    SYNTHESIS = "synthesis"
    PLANNING = "planning"
    ACTION = "action"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


# --- Canonical primary_type string ids (handlers register against these later) ---


class IntentType:
    """Stable ``primary_type`` wire strings. Prefer new constants here over magic literals."""

    UNKNOWN = "unknown"
    RETRIEVAL_WEATHER = "retrieval.weather"
    RETRIEVAL_CRYPTO = "retrieval.crypto"
    SYNTHESIS_SUMMARY = "synthesis.summary"
    PLANNING_GOAL = "planning.goal"
    CONVERSATION_GREETING = "conversation.greeting"


IntentRoute = Literal["template", "dynamic", "clarify"]

_SLOT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SECONDARY_TYPE_WIRE_RE = re.compile(r"^[a-z][a-z0-9_.]*$")


class IntentClassificationResult(BaseModel):
    """
    Output of the intent tier (rules / LLM / merge). Downstream registry resolves
    ``primary_type`` + ``route`` to a template handler or hands off to Planner/workflow.
    """

    model_config = ConfigDict(extra="forbid")

    primary_family: IntentFamily = Field(
        ...,
        description="Dominant behavioral family for this utterance.",
    )
    primary_type: str = Field(
        default=IntentType.UNKNOWN,
        min_length=1,
        max_length=128,
        description="Fine-grained type id (e.g. retrieval.weather); open-ended string.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="0..1 confidence for (primary_family, primary_type) pair.",
    )
    slots: dict[str, Any] = Field(
        default_factory=dict,
        description="Flat extraction map; keys MUST be snake_case ASCII.",
    )
    route: IntentRoute = Field(
        ...,
        description="template=preset handler, dynamic=Planner/skill path, clarify=ask user.",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description="Short machine codes for telemetry (e.g. rule_hit, llm_parse_ok).",
    )
    secondary_types: List[str] = Field(
        default_factory=list,
        description="Extra intent-type wire ids when the model proposes multi-label types.",
    )
    family_candidates: List[IntentFamily] = Field(
        default_factory=list,
        validation_alias=AliasChoices("families", "family_candidates"),
        description="Additional IntentFamily labels from multi-label LLM output; merged via policy.",
    )

    @field_validator("secondary_types")
    @classmethod
    def _secondary_types_wire(cls, v: List[str]) -> List[str]:
        for t in v:
            if not isinstance(t, str) or not _SECONDARY_TYPE_WIRE_RE.match(t):
                raise ValueError(
                    f"invalid secondary_type {t!r}: use lowercase wire ids (letters, digits, _, .)"
                )
        return v

    @field_validator("slots")
    @classmethod
    def _slots_keys_snake(cls, v: dict[str, Any]) -> dict[str, Any]:
        for k in v:
            if not isinstance(k, str):
                raise TypeError(f"slot keys must be str, got {type(k).__name__}")
            if not _SLOT_KEY_RE.match(k):
                raise ValueError(
                    f"invalid slot key {k!r}: use snake_case ASCII starting with a letter"
                )
        return v


def default_unknown_result(
    *,
    route: IntentRoute = "dynamic",
    reason_codes: Optional[list[str]] = None,
) -> IntentClassificationResult:
    """Factory for a conservative UNKNOWN classification (no side effects)."""
    return IntentClassificationResult(
        primary_family=IntentFamily.UNKNOWN,
        primary_type=IntentType.UNKNOWN,
        confidence=0.0,
        slots={},
        route=route,
        reason_codes=list(reason_codes or ["default_unknown"]),
    )
