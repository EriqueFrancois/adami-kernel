from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from adami_kernel.cortex.decision_processor import DecisionProcessor
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.peripheral.report_studio.report_store import ReportConfigStore


def test_report_store_creates_defaults(tmp_path: Path) -> None:
    sb = SecondBrainManager(str(tmp_path / "brain"))
    store = ReportConfigStore(sb)
    store.ensure_defaults()
    items = store.list_configs()
    assert {i["report_type"] for i in items} == {"daily", "weekly", "monthly"}
    daily = store.load("daily")
    assert daily.report_type == "daily"


@pytest.mark.asyncio
async def test_report_set_and_show_via_decision_processor(tmp_path: Path) -> None:
    # kernel context mock
    brain = tmp_path / "brain"
    sb = SecondBrainManager(str(brain))

    sent = {"text": None}

    async def _send_reply(chat_id: str, text: str, platform: str = "cli"):
        sent["text"] = text

    kernel = SimpleNamespace(
        _send_reply=_send_reply,
        intent_router=MagicMock(),
        intent_template_registry=None,
        session_locks={},
        active_sessions={},
        episodic_memory=None,
        second_brain=sb,
    )
    # KernelContext is a protocol-ish class; DecisionProcessor only accesses attrs.
    dp = DecisionProcessor(kernel=kernel)  # type: ignore[arg-type]

    # direct call handler (SYSTEM_ACTION dispatch path)
    await dp._handle_report_action(
        '/report set daily {"schedule":{"timezone":"UTC","publish_time_hhmm":"08:30"}}',
        "cli",
        "cli",
    )
    assert (
        sent["text"]
        and "daily" in sent["text"]
        and "UTC" in sent["text"]
        and "08:30" in sent["text"]
    )

    await dp._handle_report_action("/report show daily", "cli", "cli")
    assert sent["text"] and "```json" in sent["text"]
    assert '"timezone": "UTC"' in sent["text"]


@pytest.mark.asyncio
async def test_report_help_mentions_wizard(tmp_path: Path) -> None:
    brain = tmp_path / "brain"
    sb = SecondBrainManager(str(brain))

    sent = {"text": None}

    async def _send_reply(chat_id: str, text: str, platform: str = "cli"):
        sent["text"] = text

    kernel = SimpleNamespace(
        _send_reply=_send_reply,
        intent_router=MagicMock(),
        intent_template_registry=None,
        session_locks={},
        active_sessions={},
        episodic_memory=None,
        second_brain=sb,
    )
    dp = DecisionProcessor(kernel=kernel)  # type: ignore[arg-type]

    await dp._handle_report_action("/report help", "cli", "cli")
    assert sent["text"]
    assert "report:wizard" in sent["text"].lower()
    assert "telegram/discord" in sent["text"].lower()


@pytest.mark.asyncio
async def test_report_run_telegram_skips_generated_path_when_body_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from adami_kernel.peripheral.report_studio.report_generator import GeneratedReport
    from adami_kernel.peripheral.report_studio.report_renderer import RenderedReport

    brain = tmp_path / "brain"
    sb = SecondBrainManager(str(brain))
    ReportConfigStore(sb).ensure_defaults()
    cfg = ReportConfigStore(sb).load("daily")
    cfg.enabled = True
    ReportConfigStore(sb).save(cfg)

    sent: list[str] = []

    async def _send_reply(chat_id: str, text: str, platform: str = "telegram", **kwargs):
        sent.append(text)

    kernel = SimpleNamespace(
        _send_reply=_send_reply,
        intent_router=MagicMock(),
        intent_template_registry=None,
        session_locks={},
        active_sessions={},
        episodic_memory=None,
        second_brain=sb,
        toolbox=None,
        router=None,
        bus=None,
    )
    dp = DecisionProcessor(kernel=kernel)  # type: ignore[arg-type]

    async def _fake_gen(**kwargs):
        return GeneratedReport(
            rendered=RenderedReport(
                title="Daily",
                body_md="# Hello\n\nBody of the briefing.",
                template_path=None,
            ),
            data={},
        )

    monkeypatch.setattr(
        "adami_kernel.peripheral.report_studio.report_generator.generate_fixed_blocks_report",
        _fake_gen,
    )
    monkeypatch.setattr(
        "adami_kernel.config.settings.ADAMI_SIM_TRACE_EXPORT_ENABLED",
        False,
        raising=False,
    )

    await dp._handle_report_action("/report run daily", "1", "telegram")
    joined = "\n".join(sent)
    assert "Body of the briefing" in joined
    assert "SecondBrain" not in joined
    assert not any("report-" in t and t.endswith(".md`") for t in sent)
