"""Pydantic models aligned with ``docs/demo/openapi.yaml``."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ScenarioId = Literal[
    "what-adami-can-do",
    "goal-planning",
    "analyze-problem",
    "memory-mechanism",
    "reflect-improve",
    "readonly-organize",
    "freeform",
]

LocaleId = Literal["en", "zh-CN"]
AcceptedMode = Literal["live", "fake"]
StatusPhase = Literal["analyzing", "organizing", "answering"]
FinishReason = Literal["completed", "cancelled", "timeout", "error"]
ReleasedKind = Literal["slot", "queue"]
HealthStatus = Literal["ok", "degraded", "unavailable"]
ErrorCode = Literal[
    "rate_limited",
    "turn_limit",
    "input_too_long",
    "queue_full",
    "wait_timeout",
    "session_expired",
    "already_running",
    "unavailable",
    "tool_denied",
    "csrf_denied",
    "origin_denied",
]

SCENARIO_IDS: tuple[str, ...] = (
    "what-adami-can-do",
    "goal-planning",
    "analyze-problem",
    "memory-mechanism",
    "reflect-improve",
    "readonly-organize",
    "freeform",
)

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "explain_capability",
        "plan_outline",
        "scratchpad_read",
        "scratchpad_write",
        "reflect",
        "organize_notes",
    }
)

DENIED_TOOL_MARKERS: tuple[str, ...] = (
    "execute_command",
    "write_file",
    "web_search",
    "skill market",
    "skill_market",
    "/market/",
    "telegram",
    "discord",
    "evolution",
    "idle train",
    "idle_train",
    "toolboxmanager",
    "decisionprocessor",
    "hybridllmrouter",
    "mcp",
    "rpa",
    "ssh",
    "git commit",
    "git push",
    "shell",
    "subprocess",
    "os.system",
)


class SessionCreateRequest(BaseModel):
    locale: LocaleId = "en"


class SessionCreateResponse(BaseModel):
    expiresAt: str
    turnsRemaining: int
    maxTurns: int
    csrfToken: str
    llmMode: AcceptedMode
    disclaimer: Literal["capability-demo"] = "capability-demo"


class TurnRequest(BaseModel):
    scenarioId: ScenarioId
    message: str = Field(default="", max_length=20000)
    clientTurnId: str | None = None


class ScenarioItem(BaseModel):
    id: ScenarioId
    title: str
    description: str
    disclaimer: str


class FallbackPayload(BaseModel):
    reason: str
    label: Literal["canned-demo"] = "canned-demo"
    title: str
    body: str
    scenarioId: ScenarioId


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    fallback: FallbackPayload | None = None


class HealthBody(BaseModel):
    status: HealthStatus
    disclaimer: Literal["capability-demo"] = "capability-demo"
