"""Readonly demo tools (session scratchpad only)."""

from __future__ import annotations

from adami_kernel.demo.models import ALLOWED_TOOLS, DENIED_TOOL_MARKERS


def is_allowed_tool(name: str) -> bool:
    return name.strip() in ALLOWED_TOOLS


def find_denied_marker(text: str) -> str | None:
    blob = (text or "").lower()
    for marker in DENIED_TOOL_MARKERS:
        if marker in blob:
            return marker
    return None
