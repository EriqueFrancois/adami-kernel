"""
Step 7 acceptance: Discord/Telegram notification path metrics (OTEL counters + wiring).

Run:
  poetry run python -m pytest tests/test_acceptance_messenger_metrics_step7.py -q
"""

from __future__ import annotations

from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ac7_metrics_module_defines_otel_counters() -> None:
    text = (_root() / "src" / "adami_kernel" / "observability" / "messenger_metrics.py").read_text(
        encoding="utf-8"
    )
    assert "adami.kernel.messenger.notifications" in text
    assert "adami.kernel.messenger.notification_retries" in text
    assert "def record_notification_send" in text
    assert "def record_notification_retry" in text
    assert "messaging.platform" in text and "messaging.outcome" in text


def test_ac7_discord_nerve_wires_send_metrics() -> None:
    text = (_root() / "src" / "adami_kernel" / "nexus" / "discord_nerve.py").read_text(
        encoding="utf-8"
    )
    assert "record_notification_send" in text
    assert (
        "async def send_interactive_buttons(self, channel_id: str, text: str, buttons: List[Dict]) -> bool:"
        in text
    )


def test_ac7_telegram_sensory_wires_send_and_retry_metrics() -> None:
    text = (_root() / "src" / "adami_kernel" / "nexus" / "telegram_sensory.py").read_text(
        encoding="utf-8"
    )
    assert "record_notification_send" in text
    assert "record_notification_retry" in text
    assert "ui_thought_resend" in text


def test_ac7_lifecycle_boot_queue_wires_retries() -> None:
    text = (_root() / "src" / "adami_kernel" / "core" / "lifecycle_manager.py").read_text(
        encoding="utf-8"
    )
    assert "record_notification_retry" in text
    assert "boot_pending_queue" in text


def test_ac7_i18n_telegram_buttons_send_fail_locale_parity() -> None:
    en = (_root() / "src" / "adami_kernel" / "i18n" / "locales" / "en" / "common.json").read_text(
        encoding="utf-8"
    )
    zh = (
        _root() / "src" / "adami_kernel" / "i18n" / "locales" / "zh-Hans" / "common.json"
    ).read_text(encoding="utf-8")
    key = "boot.log.telegram_buttons_send_fail"
    assert key in en and key in zh
