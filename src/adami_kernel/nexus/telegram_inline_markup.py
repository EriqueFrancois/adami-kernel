"""Telegram ``inline_keyboard`` layout helpers (no aiogram dependency)."""

from __future__ import annotations

from typing import Any, Dict, List


def inline_keyboard_one_button_per_row(buttons: List[Dict[str, Any]]) -> List[List[Dict[str, str]]]:
    """One ``InlineKeyboardButton`` per row so labels are not squeezed into unreadable columns."""
    return [[{"text": str(b["text"]), "callback_data": str(b["callback_data"])}] for b in buttons]
