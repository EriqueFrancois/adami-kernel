# -*- coding: utf-8 -*-
"""Boundary: second-party / external summaries → UI locale via ``translate_text_async``."""

from __future__ import annotations

import asyncio
import uuid

import pytest

import adami_kernel.i18n.translate as translate_mod
from adami_kernel.i18n.external_text import translate_external_summary_for_ui


def test_external_summary_returns_original_when_translate_disabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    monkeypatch.setattr(translate_mod, "_settings_translate_enabled", lambda: False)
    calls: list[str] = []

    async def llm(prompt: str) -> str:
        calls.append(prompt)
        return "SHOULD_NOT_USE"

    async def _run() -> str:
        return await translate_external_summary_for_ui(
            "snippet for ui",
            target_locale="zh-Hans",
            call_llm=llm,
        )

    out = asyncio.run(_run())
    assert out == "snippet for ui"
    assert calls == []


def test_external_summary_on_llm_failure_returns_original(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    monkeypatch.setattr(translate_mod, "_settings_translate_enabled", lambda: True)

    async def llm(_prompt: str) -> str:
        raise RuntimeError("llm down")

    text = f"uniq-{uuid.uuid4().hex}"

    async def _run() -> str:
        return await translate_external_summary_for_ui(
            text,
            target_locale="ja",
            call_llm=llm,
            trace_id="t_ext_summary_test",
        )

    assert asyncio.run(_run()) == text
