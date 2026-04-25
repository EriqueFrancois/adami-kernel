"""Dashboard payload fields so the web console tracks ``effective_ui_default_locale()``."""

from __future__ import annotations

from typing import Any, Dict

from adami_kernel.config import settings


def dashboard_locale_fields() -> Dict[str, Any]:
    """Kernel UI locale (BCP-47-ish) and supported list for frontend catalogs."""
    return {
        "ui_locale": settings.effective_ui_default_locale(),
        "supported_locales": list(settings.ADAMI_SUPPORTED_LOCALES),
    }
