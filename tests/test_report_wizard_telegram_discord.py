from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from adami_kernel.nexus.discord_nerve import DiscordNerve
from adami_kernel.nexus.telegram_sensory import TelegramSensory


class _FakeTelegramMessage:
    def __init__(self, chat_id: int, text: str):
        self.chat = SimpleNamespace(id=chat_id)
        self.text = text
        self.content_type = "text"
        self._answers: list[str] = []

    async def answer(self, text: str):
        self._answers.append(text)


@pytest.mark.asyncio
async def test_telegram_report_wizard_text_entry_opens_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []

    async def _publish(ev):
        published.append(ev)

    t = TelegramSensory(publish_func=_publish)
    # avoid touching real bot; capture interactive prompt instead
    sent: dict[str, object] = {}

    async def _send_interactive_buttons(chat_id: int, text: str, buttons):
        sent["chat_id"] = chat_id
        sent["text"] = text
        sent["buttons"] = buttons

    monkeypatch.setattr(t, "send_interactive_buttons", _send_interactive_buttons)

    msg = _FakeTelegramMessage(chat_id=123, text="report:wizard")
    await t._handle_text(msg)  # type: ignore[arg-type]

    assert sent["chat_id"] == 123
    intro = str(sent["text"]).lower()
    assert "report studio" in intro
    assert ("wizard" in intro) or ("向导" in str(sent["text"]))
    buttons = sent["buttons"]
    assert isinstance(buttons, list)
    assert any(b.get("callback_data") == "report:type:daily" for b in buttons)
    assert published == []


@pytest.mark.asyncio
async def test_telegram_report_wizard_schedule_input_publishes_report_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []

    async def _publish(ev):
        published.append(ev)

    t = TelegramSensory(publish_func=_publish)

    # seed wizard state to await schedule input
    t._report_wizard["123"] = {
        "stage": "await_schedule",
        "report_type": "daily",
        "sections": {
            "general_news": True,
            "sports": False,
            "politics": True,
            "military": False,
            "tech_news": True,
        },
    }

    msg = _FakeTelegramMessage(chat_id=123, text="UTC 08:30")
    await t._handle_text(msg)  # type: ignore[arg-type]

    assert len(published) == 1
    ev = published[0]
    # BaseNerve.create_event returns AdamiEvent-like object with payload dict
    payload = getattr(ev, "payload", None) or {}
    task = payload.get("task") or ""
    assert task.startswith("/report set daily ")
    updates = json.loads(task.split(" ", 3)[3])
    assert updates["schedule"]["timezone"] == "UTC"
    assert updates["schedule"]["publish_time_hhmm"] == "08:30"
    assert updates["sections"]["general_news"] is True
    assert updates["sections"]["politics"] is True
    assert updates["sections"]["tech_news"] is True


@pytest.mark.asyncio
async def test_discord_report_wizard_callback_sets_await_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = DiscordNerve(publish_func=AsyncMock())
    # avoid requiring the bot to be ready or network; capture send_interactive_buttons
    sent: list[dict] = []

    async def _send_interactive_buttons(channel_id: str, text: str, buttons):
        sent.append({"channel_id": channel_id, "text": text, "buttons": buttons})

    monkeypatch.setattr(d, "send_interactive_buttons", _send_interactive_buttons)

    # 1) open wizard
    interaction_open = SimpleNamespace(
        channel_id=456,
        data={"custom_id": "report:open"},
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    await d._handle_report_callback(interaction_open)  # type: ignore[arg-type]
    assert d._report_wizard["456"]["stage"] == "choose_type"

    # 2) choose type
    interaction_type = SimpleNamespace(
        channel_id=456,
        data={"custom_id": "report:type:weekly"},
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    await d._handle_report_callback(interaction_type)  # type: ignore[arg-type]
    assert d._report_wizard["456"]["report_type"] == "weekly"
    assert d._report_wizard["456"]["stage"] == "choose_sections"

    # 3) move to schedule
    interaction_next = SimpleNamespace(
        channel_id=456,
        data={"custom_id": "report:next_schedule"},
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    await d._handle_report_callback(interaction_next)  # type: ignore[arg-type]
    assert d._report_wizard["456"]["stage"] == "await_schedule"
