"""SystemDiagnostics + boot adapter: missing modules listed; no crash without evolution_engine."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from adami_kernel.orchestrator.diagnostics import SystemDiagnostics
from adami_kernel.orchestrator.diagnostics_view import ComponentsKernelView


def test_components_kernel_view_maps_bus() -> None:
    view = ComponentsKernelView({"bus": "BUS"})
    assert view.bus == "BUS"
    assert view.nerves == []


def test_startup_check_lists_missing_cognitive() -> None:
    kernel = SimpleNamespace(
        bus=object(),
        memory=object(),
        router=object(),
        evolution_engine=SimpleNamespace(dynamic_skills={}),
        toolbox=object(),
        subconscious=object(),
        meta_cortex=object(),
        woofish=None,
        endocrine=None,
        self_model=object(),
        curiosity=None,
        sub_agent_manager=object(),
        immunity=object(),
        sensory=object(),
        telegram_nerve=object(),
        proprioception=object(),
        dlq=object(),
        nerves=[],
    )
    mock_table = MagicMock()
    with patch("adami_kernel.orchestrator.diagnostics.Table", return_value=mock_table):
        with patch("adami_kernel.orchestrator.diagnostics.console"):
            SystemDiagnostics.perform_startup_check(kernel)
    joined = " ".join(str(c) for call in mock_table.add_row.call_args_list for c in call.args)
    assert "WoofishPredictor" in joined or "Inactive" in joined or "missing" in joined.lower()
    cognitive_row = mock_table.add_row.call_args_list[1]
    cog_mount = str(cognitive_row.args[1])
    assert "WoofishPredictor" in cog_mount
    assert "CuriosityQueue" in cog_mount


def test_startup_check_without_evolution_engine() -> None:
    kernel = SimpleNamespace(
        bus=None,
        memory=None,
        router=None,
        evolution_engine=None,
        toolbox=None,
        subconscious=None,
        meta_cortex=None,
        woofish=None,
        endocrine=None,
        self_model=None,
        curiosity=None,
        sub_agent_manager=None,
        immunity=None,
        sensory=None,
        telegram_nerve=None,
        proprioception=None,
        dlq=None,
        nerves=[],
    )
    with patch("adami_kernel.orchestrator.diagnostics.Table"):
        with patch("adami_kernel.orchestrator.diagnostics.console"):
            SystemDiagnostics.perform_startup_check(kernel)
