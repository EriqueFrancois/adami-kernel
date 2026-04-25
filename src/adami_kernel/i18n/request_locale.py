from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

_request_locale: ContextVar[Optional[str]] = ContextVar("adami_request_locale", default=None)


def attach_request_locale(effective: str) -> Any:
    """Bind effective locale for the current asyncio Task; returns reset token."""
    return _request_locale.set(effective)


def reset_request_locale(token: Any) -> None:
    _request_locale.reset(token)


def get_request_locale() -> Optional[str]:
    return _request_locale.get()
