# -*- coding: utf-8 -*-
"""Step 6 翻译模块（i18n/translate）— 验收测试（自动化）

验收方案（概要）
================

1. **可导入性**：通过子模块路径加载 ``adami_kernel.i18n.translate``，不依赖在
   ``adami_kernel.i18n`` 包根导出（避免与 ``config`` / ``locale_utils`` 循环依赖）。

2. **缓存键契约**：``make_translate_cache_key`` 对同一 (text, source, target, scenario)
   稳定；**scenario** 不同则键不同（避免跨场景误命中缓存）。

3. **空输入**：空白文本不调 ``call_llm``、原样返回。

4. **审计契约**：成功翻译路径产生 ``ExperienceSink.record_tool_call``，
   ``tool_name=i18n_translate``，且 ``extra`` 含 ``scenario`` / ``cache_hit`` / ``char_len``。

5. **行为回归**：与 ``tests/test_i18n_translate.py`` 单测互补（禁用、同源 locale、
   缓存命中、超时/异常回退、超长、mock 审计）；本文件只做验收级契约与导入检查。

执行：

  poetry run pytest tests/test_acceptance_i18n_step6_translate.py \\
    tests/test_i18n_translate.py -v

全量门禁仍建议：``pytest -m "not integration"``。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import adami_kernel.i18n.translate as translate_mod
from adami_kernel.i18n.translate import make_translate_cache_key, translate_text_async


def test_step6_translate_submodule_loads_via_importlib() -> None:
    m = importlib.import_module("adami_kernel.i18n.translate")
    assert hasattr(m, "translate_text_async")
    assert hasattr(m, "make_translate_cache_key")


def test_step6_cache_key_differs_by_scenario() -> None:
    a = make_translate_cache_key("x", "zh-Hans", scenario="report")
    b = make_translate_cache_key("x", "zh-Hans", scenario="digest")
    assert a != b


@pytest.mark.asyncio
async def test_step6_empty_and_whitespace_skip_llm(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    calls: list[int] = []

    async def llm(p: str) -> str:
        calls.append(1)
        return "bad"

    assert await translate_text_async("", target_locale="zh-Hans", call_llm=llm) == ""
    assert await translate_text_async("   \n", target_locale="zh-Hans", call_llm=llm) == "   \n"
    assert calls == []


@pytest.mark.asyncio
async def test_step6_audit_extra_contains_contract_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(translate_mod, "translate_cache_root", lambda: tmp_path / "c")
    rows: list[dict] = []

    class _Sink:
        def record_tool_call(self, **kwargs):
            rows.append(kwargs.get("extra") or {})

    monkeypatch.setattr(translate_mod, "get_experience_sink", lambda: _Sink())

    async def llm(p: str) -> str:
        return "OK"

    await translate_text_async(
        "hello",
        target_locale="de",
        call_llm=llm,
        scenario="acceptance",
        trace_id="step6-audit",
    )
    assert rows
    ex = rows[0]
    assert ex.get("scenario") == "acceptance"
    assert "target_locale" in ex
    assert "cache_hit" in ex
    assert ex.get("char_len") == len("hello")
