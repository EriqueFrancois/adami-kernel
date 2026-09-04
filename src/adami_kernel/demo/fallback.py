"""Prepared (canned) demonstration copy. Never labeled live."""

from __future__ import annotations

from adami_kernel.demo.messages import demo_t, error_message
from adami_kernel.demo.models import SCENARIO_IDS, FallbackPayload, ScenarioId


def canned_fallback(locale: str, scenario_id: ScenarioId | str, reason_code: str) -> FallbackPayload:
    sid = scenario_id if scenario_id in SCENARIO_IDS else "freeform"
    return FallbackPayload(
        reason=error_message(locale, reason_code),
        label="canned-demo",
        title=demo_t(locale, f"demo.fallback.{sid}.title"),
        body=demo_t(locale, f"demo.fallback.{sid}.body"),
        scenarioId=sid,  # type: ignore[arg-type]
    )
