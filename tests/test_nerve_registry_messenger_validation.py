"""
Step 1 验收：信使路由在 nerve 注册时 fail-fast（不在 Settings import 阶段）。

覆盖 ``_validate_messenger_routing_settings`` / ``NerveRegistry.register_default_nerves`` 前置校验。
"""

from __future__ import annotations

import pytest

from adami_kernel.config import settings
from adami_kernel.nexus.nerve_registry import (
    NerveRegistry,
    _validate_messenger_routing_settings,
)


def test_validate_telegram_token_without_chat_id_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "t" * 45, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None, raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_CHAT_ID"):
        _validate_messenger_routing_settings()


def test_validate_telegram_token_with_nonpositive_chat_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "t" * 45, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", 0, raising=False)
    with pytest.raises(RuntimeError, match="positive integer"):
        _validate_messenger_routing_settings()


def test_validate_discord_token_without_routing_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", "d" * 50, raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_USER_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_CHANNEL_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_GUILD_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_SLASH_GUILD_ID", None, raising=False)
    with pytest.raises(RuntimeError, match="no Discord routing defaults"):
        _validate_messenger_routing_settings()


def test_validate_discord_normalizes_snowflakes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", "d" * 50, raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_USER_ID", " 987654321098765432 ", raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_CHANNEL_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_GUILD_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_SLASH_GUILD_ID", None, raising=False)
    _validate_messenger_routing_settings()
    assert settings.DISCORD_DEFAULT_USER_ID == "987654321098765432"


def test_validate_discord_invalid_snowflake_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", "d" * 50, raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_USER_ID", "not-a-snowflake", raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_CHANNEL_ID", None, raising=False)
    monkeypatch.setattr(settings, "DISCORD_DEFAULT_GUILD_ID", None, raising=False)
    with pytest.raises(RuntimeError, match="numeric snowflake"):
        _validate_messenger_routing_settings()


def test_register_default_nerves_invokes_same_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DISCORD_BOT_TOKEN", None, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "t" * 45, raising=False)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None, raising=False)
    reg = NerveRegistry()
    with pytest.raises(RuntimeError, match="TELEGRAM_CHAT_ID"):
        reg.register_default_nerves(publish_func=lambda *_a, **_k: None)
