"""Load ``report_rss_feeds.json`` (whitelist RSS + DDG / GitHub tuning)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / "data" / "report_rss_feeds.json"


@lru_cache(maxsize=1)
def load_report_feed_config() -> dict:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def reload_report_feed_config() -> dict:
    load_report_feed_config.cache_clear()
    return load_report_feed_config()
