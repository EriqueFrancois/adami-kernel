from __future__ import annotations

"""One-shot sync of module-level i18n defaults from ``Settings`` (boot / reload)."""

from adami_kernel.config import settings
from adami_kernel.i18n.catalog import Translator, set_default_translator
from adami_kernel.i18n.locale_utils import normalize_locale


def bootstrap_i18n_defaults_from_settings() -> None:
    set_default_translator(
        Translator(default_locale=normalize_locale(settings.effective_ui_default_locale()))
    )
