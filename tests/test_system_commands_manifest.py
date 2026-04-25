"""Sanity checks for ``system_commands_manifest.json`` and catalog helpers."""

import re
from pathlib import Path

from adami_kernel.nexus.system_commands_catalog import (
    load_system_commands_manifest,
    telegram_command_entries,
)


def test_manifest_loads_and_telegram_commands_valid():
    m = load_system_commands_manifest()
    assert m.get("schema_version") == 1
    assert isinstance(m.get("commands"), list)
    pat = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

    tg_names: list[str] = []
    for row in m["commands"]:
        name = row.get("telegram_command")
        if not name:
            continue
        assert pat.fullmatch(name.strip().lower()), f"invalid telegram_command: {name!r}"
        tg_names.append(name.strip().lower())

    assert len(tg_names) == len(set(tg_names)), "duplicate telegram_command in manifest"
    assert len(tg_names) <= 100

    pairs = telegram_command_entries("en")
    assert pairs
    for cmd, desc in pairs:
        assert pat.fullmatch(cmd)
        assert 0 < len(desc) <= 256


def test_manifest_file_path_exists():
    p = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "adami_kernel"
        / "i18n"
        / "data"
        / "system_commands_manifest.json"
    )
    assert p.is_file()
