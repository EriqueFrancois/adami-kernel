"""步骤 15：TASK_NOTE 意图路由与匹配日志。"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

from adami_kernel.cortex.intent_router import IntentSystemToken, SemanticIntentRouter


def test_task_note_phrases_route_to_system_action_and_log(caplog):
    caplog.set_level(logging.INFO, logger="AdamI-IntentRouter")
    router = SemanticIntentRouter(MagicMock())
    samples = [
        "帮我记一下明天交报告",
        "记任务：买牛奶",
        "记一下回邮件",
        "/task 致电张三",
        "/todo",
    ]
    for text in samples:
        caplog.clear()
        kind, data = asyncio.run(router.route_task(text))
        assert kind == "SYSTEM_ACTION", text
        assert data == IntentSystemToken.TASK_NOTE.value, text
        assert any("TASK_NOTE 已匹配" in r.message for r in caplog.records), text
