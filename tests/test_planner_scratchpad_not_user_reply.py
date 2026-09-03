from __future__ import annotations

from adami_kernel.i18n import t
from adami_kernel.orchestrator.planner import (
    TaskPlanner,
    looks_like_planner_scratchpad,
)


def test_looks_like_planner_scratchpad_detects_nested_json() -> None:
    blob = (
        '{"original_task": "x", "original_user_task": "【每日晨会】",'
        ' "second_brain_snippets": "### `Inbox/report-2026-04-11.md`",'
        ' "previous_result": "{}"}'
    )
    assert looks_like_planner_scratchpad(blob) is True
    assert looks_like_planner_scratchpad({"original_task": "a", "previous_result": "b"}) is True
    assert looks_like_planner_scratchpad("BTC is 111k") is False


def test_format_result_does_not_echo_scratchpad() -> None:
    planner = TaskPlanner(
        router=None,
        evolution_engine=None,
        bus=None,
        sensitive_filter=None,
    )
    dumped = (
        '{"original_user_task": "brief", "second_brain_snippets": "old",'
        ' "previous_result": "{\\"original_task\\": \\"x\\"}"}'
    )
    out = planner._format_result(dumped)
    assert "original_user_task" not in out
    assert "second_brain_snippets" not in out
    assert out == t("planner.result.no_valid_result")
