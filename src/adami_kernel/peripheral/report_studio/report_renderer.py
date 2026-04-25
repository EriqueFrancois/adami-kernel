from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from jinja2 import Environment

from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.i18n.catalog import default_translator
from adami_kernel.i18n.locale_utils import normalize_locale, pick_first_supported
from adami_kernel.peripheral.report_studio.report_config import ReportType

logger = logging.getLogger("AdamI-ReportStudio")

# Packaged locale templates (Step 5): same structure, language-specific copy in .j2 + labels.
_PACKAGED_LOCALES_DIR = Path(__file__).resolve().parents[2] / "i18n" / "locales"


def _report_labels(
    locale: str,
    report_type: ReportType,
    *,
    period_start: str,
    period_end: str,
) -> Dict[str, str]:
    tr = default_translator()
    loc = normalize_locale(locale)
    keys = (
        ("meta_period", "report.studio.meta_period"),
        ("meta_timezone", "report.studio.meta_timezone"),
        ("meta_type", "report.studio.meta_type"),
        ("source_link", "report.studio.source_link"),
        ("section_system", "report.studio.section_system"),
        ("section_world_news", "report.studio.section_world_news"),
        ("section_ai", "report.studio.section_ai"),
        ("section_market", "report.studio.section_market"),
        ("empty_world_news", "report.studio.empty_world_news"),
        ("empty_ai", "report.studio.empty_ai"),
        ("empty_market", "report.studio.empty_market"),
        ("section_crypto", "report.studio.section_crypto"),
        ("empty_crypto", "report.studio.empty_crypto"),
        ("crypto_asof", "report.studio.crypto_asof"),
    )
    out = {alias: tr.t(k, locale=loc) for alias, k in keys}
    kind_map: Dict[ReportType, str] = {
        "daily": "report.studio.kind_daily",
        "weekly": "report.studio.kind_weekly",
        "monthly": "report.studio.kind_monthly",
    }
    out["kind_display"] = tr.t(kind_map[report_type], locale=loc)
    return out


def localized_report_title(report_type: ReportType, locale: str) -> str:
    tr = default_translator()
    loc = normalize_locale(locale)
    kind_map = {
        "daily": "report.studio.kind_daily",
        "weekly": "report.studio.kind_weekly",
        "monthly": "report.studio.kind_monthly",
    }
    kind = tr.t(kind_map[report_type], locale=loc)
    return tr.t("report.studio.title", kind=kind, locale=loc)


@dataclass
class RenderedReport:
    title: str
    body_md: str
    template_path: Optional[str]


class ReportTemplateStore:
    """Resolve `report.md.j2` by locale: SecondBrain override → packaged locale → packaged en."""

    def __init__(self, second_brain: Optional[SecondBrainManager] = None) -> None:
        self.sb = second_brain or SecondBrainManager()
        self.root = Path(self.sb.root).resolve()

    def templates_dir(self) -> Path:
        d = self.root / "System" / "working-memory" / "report_templates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _user_override_path(self, locale: str) -> Path:
        loc = normalize_locale(locale)
        return self.templates_dir() / f"report.{loc}.md.j2"

    def _packaged_template_path(self, locale: str) -> Path:
        loc = normalize_locale(locale)
        return _PACKAGED_LOCALES_DIR / loc / "report.md.j2"

    def _fallback_packaged_en(self) -> Path:
        return _PACKAGED_LOCALES_DIR / "en" / "report.md.j2"

    def load_locale_template(self, locale: str, *, supported: Tuple[str, ...]) -> Tuple[str, str]:
        """Return (template_text, resolved_path_str).

        If the requested locale file is missing under ``locales/<loc>/``, the **file**
        falls back to English ``report.md.j2``; labels are still built for the requested
        locale so section titles stay translated.
        """
        loc = pick_first_supported(locale, supported=supported, hard_fallback="en")
        override = self._user_override_path(loc)
        if override.is_file():
            text = override.read_text(encoding="utf-8")
            return text, str(override)

        packaged = self._packaged_template_path(loc)
        if packaged.is_file():
            return packaged.read_text(encoding="utf-8"), str(packaged)

        fb = self._fallback_packaged_en()
        if not fb.is_file():
            raise FileNotFoundError(f"Missing packaged report template: {fb}")
        if normalize_locale(loc) != "en":
            logger.warning(
                "[ReportStudio] missing packaged template for locale=%s; using en file %s",
                loc,
                fb,
            )
        return fb.read_text(encoding="utf-8"), str(fb)


class ReportRenderer:
    def __init__(self, second_brain: Optional[SecondBrainManager] = None) -> None:
        self.templates = ReportTemplateStore(second_brain)
        self.env = Environment(
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(
        self,
        *,
        report_type: ReportType,
        title: str,
        period_start: str,
        period_end: str,
        timezone: str,
        data: Dict[str, Any],
        locale: str,
        supported_locales: Tuple[str, ...] = ("en", "zh-Hans"),
    ) -> RenderedReport:
        labels_locale = pick_first_supported(
            locale, supported=supported_locales, hard_fallback="en"
        )
        text, path = self.templates.load_locale_template(labels_locale, supported=supported_locales)
        tpl = self.env.from_string(text)
        labels = _report_labels(
            labels_locale, report_type, period_start=period_start, period_end=period_end
        )
        body = tpl.render(
            title=title,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            timezone=timezone,
            data=data,
            labels=labels,
        )
        return RenderedReport(title=title, body_md=body.strip() + "\n", template_path=path)
