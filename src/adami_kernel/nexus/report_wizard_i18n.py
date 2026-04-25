"""Shared Report Studio wizard labels (Telegram + Discord); callback_data unchanged."""

from __future__ import annotations

from typing import Any, Dict, List

from adami_kernel.i18n.ui_static import ui_t


def report_wizard_intro() -> str:
    return ui_t("port.report.wizard_intro")


def report_type_buttons() -> List[Dict[str, str]]:
    return [
        {"text": ui_t("port.report.btn_daily"), "callback_data": "report:type:daily"},
        {"text": ui_t("port.report.btn_weekly"), "callback_data": "report:type:weekly"},
        {"text": ui_t("port.report.btn_monthly"), "callback_data": "report:type:monthly"},
        {"text": ui_t("port.report.btn_cancel"), "callback_data": "report:cancel"},
    ]


def immediate_report_intro() -> str:
    """Entry-menu path: run a report now (uses saved Report Studio config per type)."""
    return ui_t("port.report.immediate_intro")


def immediate_report_run_buttons() -> List[Dict[str, str]]:
    return [
        {"text": ui_t("port.report.btn_daily"), "callback_data": "report:now:daily"},
        {"text": ui_t("port.report.btn_weekly"), "callback_data": "report:now:weekly"},
        {"text": ui_t("port.report.btn_monthly"), "callback_data": "report:now:monthly"},
    ]


def report_sections_intro(rt: str) -> str:
    return ui_t("port.report.sections_intro", rtype=rt)


def report_section_toggle_buttons(sec: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key, label_key in (
        ("general_news", "port.report.sec_general_news"),
        ("sports", "port.report.sec_sports"),
        ("politics", "port.report.sec_politics"),
        ("military", "port.report.sec_military"),
        ("tech_news", "port.report.sec_tech_news"),
    ):
        mark = "✅" if sec.get(key) else "❌"
        rows.append(
            {
                "text": f"{ui_t(label_key)} {mark}",
                "callback_data": f"report:toggle:{key}",
            }
        )
    rows.append(
        {
            "text": ui_t("port.report.btn_next_schedule"),
            "callback_data": "report:next_schedule",
        }
    )
    rows.append({"text": ui_t("port.report.btn_cancel"), "callback_data": "report:cancel"})
    return rows
