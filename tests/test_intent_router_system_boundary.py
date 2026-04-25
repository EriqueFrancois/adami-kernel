"""系统指令 WRITING / REPORT 边界：普通长句不得误触（与 intent_router_regex_bundle 同步）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.cortex.intent_router import IntentSystemToken, SemanticIntentRouter


@pytest.mark.asyncio
async def test_writing_topic_sentence_not_writing_studio():
    r = SemanticIntentRouter(MagicMock(call_llm=AsyncMock(return_value="[DIRECT_ANSWER] ok")))
    tag, data = await r.route_task("写作时怎样列提纲更有效")
    assert not (tag == "SYSTEM_ACTION" and data == IntentSystemToken.WRITING.value)


@pytest.mark.asyncio
async def test_report_workplace_sentence_not_report_studio():
    r = SemanticIntentRouter(MagicMock(call_llm=AsyncMock(return_value="[DIRECT_ANSWER] ok")))
    tag, data = await r.route_task("报告老板说我迟到了，该怎么回复")
    assert not (tag == "SYSTEM_ACTION" and data == IntentSystemToken.REPORT.value)


@pytest.mark.asyncio
async def test_report_natural_list_still_matches():
    r = SemanticIntentRouter(MagicMock(call_llm=AsyncMock(return_value="noop")))
    tag, data = await r.route_task("报告 list")
    assert tag == "SYSTEM_ACTION"
    assert data == IntentSystemToken.REPORT.value


@pytest.mark.asyncio
async def test_slash_report_help_matches():
    r = SemanticIntentRouter(MagicMock(call_llm=AsyncMock(return_value="noop")))
    tag, data = await r.route_task("/report help")
    assert tag == "SYSTEM_ACTION"
    assert data == IntentSystemToken.REPORT.value


@pytest.mark.asyncio
async def test_writing_colon_form_matches():
    r = SemanticIntentRouter(MagicMock(call_llm=AsyncMock(return_value="noop")))
    tag, data = await r.route_task("写作：摘要")
    assert tag == "SYSTEM_ACTION"
    assert data == IntentSystemToken.WRITING.value
