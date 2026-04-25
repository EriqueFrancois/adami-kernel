"""步骤 19：search_similar_skill（SkillFactory Tier3）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from adami_kernel.hippocampus.second_brain import (
    SecondBrainManager,
    _description_overlap_tokens,
    _keyword_overlap_score,
)


def test_keyword_overlap_score_counts_path_and_body():
    sc = _keyword_overlap_score(
        ["weather", "北京"],
        "Resources/tools/weather_fetch.py",
        "def fetch_weather(city='北京'): pass",
    )
    assert sc > 0


def test_description_overlap_tokens_dedupes():
    toks = _description_overlap_tokens("查询 weather 与 Weather API")
    assert "weather" in [t.lower() for t in toks] or "Weather" in toks


def test_search_similar_skill_returns_best_file(tmp_path: Path):
    res = tmp_path / "Resources" / "lib"
    res.mkdir(parents=True)
    (res / "crypto_price.py").write_text(
        "def get_btc_price():\n    '''bitcoin ETH ticker'''\n    return 0\n",
        encoding="utf-8",
    )
    (res / "notes.md").write_text("# 无关\n", encoding="utf-8")
    sb = SecondBrainManager(str(tmp_path))

    async def _run():
        return await sb.search_similar_skill("创建 bitcoin 与 ETH 价格查询技能")

    out = asyncio.run(_run())
    assert out is not None
    assert "Tier3 brain fallback" in out
    assert "crypto_price.py" in out
    assert "bitcoin" in out.lower() or "btc" in out.lower()


def test_search_similar_skill_empty_when_no_match(tmp_path: Path):
    (tmp_path / "Resources").mkdir(parents=True)
    (tmp_path / "Resources" / "x.py").write_text("a = 1\n", encoding="utf-8")
    sb = SecondBrainManager(str(tmp_path))

    async def _run():
        return await sb.search_similar_skill("zzzznonexistenttokenqqqq")

    assert asyncio.run(_run()) is None


def test_second_brain_has_async_search_similar_skill():
    """与 SkillFactory 约定：`search_similar_skill` 为 async 且可 await（避免 Tier3 AttributeError）。"""
    sb = SecondBrainManager(str(Path.cwd()))
    assert callable(getattr(sb, "search_similar_skill", None))
    assert asyncio.iscoroutinefunction(SecondBrainManager.search_similar_skill)
