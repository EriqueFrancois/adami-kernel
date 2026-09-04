"""User-visible Demo strings via shipped i18n catalogs (no bare CJK in Python)."""

from __future__ import annotations

from adami_kernel.i18n.catalog import t

_ERROR_KEYS: dict[str, str] = {
    "rate_limited": "demo.error.rate_limited",
    "turn_limit": "demo.error.turn_limit",
    "input_too_long": "demo.error.input_too_long",
    "queue_full": "demo.error.queue_full",
    "wait_timeout": "demo.error.wait_timeout",
    "session_expired": "demo.error.session_expired",
    "already_running": "demo.error.already_running",
    "unavailable": "demo.error.unavailable",
    "tool_denied": "demo.error.tool_denied",
    "csrf_denied": "demo.error.csrf_denied",
    "origin_denied": "demo.error.origin_denied",
    "task_timeout": "demo.error.task_timeout",
    "model_failed": "demo.error.model_failed",
    "cancelled": "demo.error.cancelled",
    "disclaimer": "demo.disclaimer",
}


def demo_t(locale: str, key: str) -> str:
    return t(key, locale=locale)


def error_message(locale: str, code: str) -> str:
    key = _ERROR_KEYS.get(code) or "demo.error.unavailable"
    return demo_t(locale, key)
