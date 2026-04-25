from __future__ import annotations

from adami_kernel.nexus.telegram_inline_markup import inline_keyboard_one_button_per_row


def test_inline_keyboard_one_button_per_row_layout() -> None:
    rows = inline_keyboard_one_button_per_row(
        [
            {"text": "Daily", "callback_data": "report:type:daily"},
            {"text": "Weekly", "callback_data": "report:type:weekly"},
        ]
    )
    assert rows == [
        [{"text": "Daily", "callback_data": "report:type:daily"}],
        [{"text": "Weekly", "callback_data": "report:type:weekly"}],
    ]
