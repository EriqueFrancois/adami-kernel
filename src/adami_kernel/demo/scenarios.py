"""Guided demo scenario catalog."""

from __future__ import annotations

from adami_kernel.demo.messages import demo_t
from adami_kernel.demo.models import SCENARIO_IDS, ScenarioItem


def list_scenarios(locale: str) -> list[ScenarioItem]:
    disc = demo_t(locale, "demo.disclaimer")
    items: list[ScenarioItem] = []
    for sid in SCENARIO_IDS:
        items.append(
            ScenarioItem(
                id=sid,  # type: ignore[arg-type]
                title=demo_t(locale, f"demo.scenario.{sid}.title"),
                description=demo_t(locale, f"demo.scenario.{sid}.description"),
                disclaimer=disc,
            )
        )
    return items
