"""Startup / console copy tied to ``settings.effective_ui_default_locale()``."""

from __future__ import annotations

from typing import Any

from adami_kernel.config import settings
from adami_kernel.i18n import t


def boot_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)
