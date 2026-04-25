"""Guard: 城市/主题「介绍」不得误触自我介绍快路径（见 intent_router_regex_bundle fast[1] / intro_trigger）。"""

from __future__ import annotations

import json
import re
from pathlib import Path


def _patterns():
    root = Path(__file__).resolve().parents[1] / "src" / "adami_kernel" / "i18n" / "data"
    b = json.loads((root / "intent_router_regex_bundle.json").read_text(encoding="utf-8"))
    fast_intro = re.compile(b["fast"][1], re.I)
    intro = re.compile(b["helpers"]["intro_trigger"], re.I)
    return fast_intro, intro


def test_place_intro_not_self_intro_fast_pattern():
    fast_intro, intro = _patterns()
    for text in ("请介绍北京", "介绍一下巴黎", "请介绍一下东京的历史", "介绍杭州的美食"):
        assert not fast_intro.search(text), text
        assert not intro.search(text), text


def test_self_intro_phrases_still_match():
    fast_intro, intro = _patterns()
    for text in (
        "请介绍你自己",
        "请介绍一下你自己",
        "介绍一下你自己",
        "你是谁",
        "自我介绍",
        "关于你？",
    ):
        assert fast_intro.search(text) or intro.search(text), text
