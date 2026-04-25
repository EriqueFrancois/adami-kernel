from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import adami_kernel.i18n.translate as translate_mod
from adami_kernel.i18n.translate import make_translate_cache_key, translate_text_async


def test_make_translate_cache_key_stable() -> None:
    k1 = make_translate_cache_key("hello", "zh-Hans", source_locale="en", scenario="digest")
    k2 = make_translate_cache_key("hello", "zh-Hans", source_locale="en", scenario="digest")
    k3 = make_translate_cache_key("hello", "zh-Hans", scenario="digest")
    assert k1 == k2
    assert k1 != k3


@pytest.mark.asyncio
async def test_translate_disabled_returns_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    monkeypatch.setattr(translate_mod, "_settings_translate_enabled", lambda: False)
    calls: list[str] = []

    async def llm(p: str) -> str:
        calls.append(p)
        return "SHOULD_NOT_USE"

    out = await translate_text_async("alpha", target_locale="zh-Hans", call_llm=llm)
    assert out == "alpha"
    assert calls == []


@pytest.mark.asyncio
async def test_translate_same_locale_skips_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    calls: list[str] = []

    async def llm(p: str) -> str:
        calls.append(p)
        return "x"

    out = await translate_text_async(
        "same",
        target_locale="en",
        call_llm=llm,
        source_locale="en",
    )
    assert out == "same"
    assert calls == []


@pytest.mark.asyncio
async def test_translate_cache_hit_skips_second_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    monkeypatch.setattr(translate_mod, "_settings_translate_cache_ttl_sec", lambda: 3600.0)
    n = {"i": 0}

    async def llm(p: str) -> str:
        n["i"] += 1
        return "cached-value"

    a = await translate_text_async("body", target_locale="zh-Hans", call_llm=llm, scenario="report")
    b = await translate_text_async("body", target_locale="zh-Hans", call_llm=llm, scenario="report")
    assert a == "cached-value" == b
    assert n["i"] == 1


@pytest.mark.asyncio
async def test_translate_timeout_returns_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")

    async def llm(p: str) -> str:
        await asyncio.sleep(10.0)
        return "late"

    out = await translate_text_async(
        "orig-timeout",
        target_locale="zh-Hans",
        call_llm=llm,
        timeout_sec=0.05,
    )
    assert out == "orig-timeout"


@pytest.mark.asyncio
async def test_translate_llm_error_returns_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")

    async def llm(p: str) -> str:
        raise RuntimeError("boom")

    out = await translate_text_async("orig-err", target_locale="zh-Hans", call_llm=llm)
    assert out == "orig-err"


@pytest.mark.asyncio
async def test_translate_too_long_returns_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    monkeypatch.setattr(translate_mod, "_settings_translate_max_chars", lambda: 5)

    async def llm(p: str) -> str:
        return "nope"

    out = await translate_text_async("12345678", target_locale="zh-Hans", call_llm=llm)
    assert out == "12345678"


@pytest.mark.asyncio
async def test_translate_records_experience_tool_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    recorded: list[dict] = []

    class _Sink:
        def record_tool_call(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(translate_mod, "get_experience_sink", lambda: _Sink())

    async def llm(p: str) -> str:
        return "done"

    await translate_text_async("x", target_locale="fr", call_llm=llm, trace_id="tid-1")
    assert recorded, "record_tool_call should run"
    assert recorded[0].get("tool_name") == "i18n_translate"
    assert recorded[0].get("ok") is True
