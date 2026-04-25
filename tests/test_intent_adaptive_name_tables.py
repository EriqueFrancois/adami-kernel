from __future__ import annotations

from adami_kernel.cortex.intent_adaptive.name_tables import (
    resolve_city_from_text,
    resolve_crypto_asset_from_text,
)


def test_resolve_city_chengdu_zh() -> None:
    c = resolve_city_from_text("帮我查询成都市今天的天气", locale="zh-Hans")
    assert c is not None
    assert c.country == "CN"
    assert c.display_name == "成都"
    assert c.api_name in ("成都", "Chengdu")


def test_resolve_city_major_global_en() -> None:
    c = resolve_city_from_text("Weather in London today", locale="en")
    assert c is not None
    assert c.display_name == "London"


def test_resolve_crypto_btc_zh() -> None:
    a = resolve_crypto_asset_from_text("请查询现在比特币的价格", locale="zh-Hans")
    assert a is not None
    assert a.symbol == "BTC"
    assert a.coingecko_id == "bitcoin"


def test_resolve_crypto_eth_en() -> None:
    a = resolve_crypto_asset_from_text("ETH price please", locale="en")
    assert a is not None
    assert a.symbol == "ETH"
    assert a.coingecko_id == "ethereum"


def test_resolve_crypto_sol_zh() -> None:
    a = resolve_crypto_asset_from_text("索拉纳现在多少钱", locale="zh-Hans")
    assert a is not None
    assert a.symbol == "SOL"
    assert a.coingecko_id == "solana"


def test_resolve_crypto_doge_en() -> None:
    a = resolve_crypto_asset_from_text("dogecoin price", locale="en")
    assert a is not None
    assert a.symbol == "DOGE"
    assert a.coingecko_id == "dogecoin"
