"""阶段 2：按序 mock inject（不启 Docker / Sim）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from adami_kernel.integration.sim.replay import (
    load_ndjson_records,
    replay_inject,
    validate_phase1_records,
)
from adami_kernel.nexus.event import AdamiEvent

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.asyncio
async def test_replay_inject_collects_events() -> None:
    recs = load_ndjson_records(FIXTURES / "golden_trace.ndjson")
    validate_phase1_records(recs)
    collected: list[AdamiEvent] = []

    async def inject(ev: AdamiEvent) -> None:
        collected.append(ev)

    await replay_inject(recs, inject)
    assert len(collected) == 3
    assert collected[0].trace_id == "golden-1"
    assert collected[0].payload.get("task") == "hello"
    assert collected[1].payload.get("phase") == "route"
