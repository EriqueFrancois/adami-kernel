"""json-repair is a declared dependency; parser flag should be true after install."""

from __future__ import annotations


def test_json_repair_import_and_flag() -> None:
    import json_repair  # noqa: F401

    from adami_kernel.cortex.tools.json_parser import JSON_REPAIR_AVAILABLE

    assert JSON_REPAIR_AVAILABLE is True
