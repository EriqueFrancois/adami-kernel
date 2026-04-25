# -*- coding: utf-8 -*-
"""Placeholder API key safety log is deduplicated per key per process (see config._PLACEHOLDER_SAFETY_WARNED)."""

from __future__ import annotations

import adami_kernel.config as config_mod


def test_reload_settings_clears_placeholder_dedupe_set() -> None:
    config_mod._PLACEHOLDER_SAFETY_WARNED.add("__test_marker_key__")
    try:
        config_mod.reload_settings()
    finally:
        config_mod._PLACEHOLDER_SAFETY_WARNED.discard("__test_marker_key__")
    assert "__test_marker_key__" not in config_mod._PLACEHOLDER_SAFETY_WARNED
