from __future__ import annotations

import json

import pytest

from adami_kernel import config as config_mod
from adami_kernel.mcp.config_loader import load_mcp_server_specs


def test_load_mcp_server_specs_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_SERVERS_JSON", None)
    assert load_mcp_server_specs() == []


def test_load_mcp_server_specs_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "name": "demo",
            "image": "demo:latest",
            "command": ["python", "-m", "x"],
            "args": ["--a", "b"],
            "env": {"FOO": "bar"},
            "workdir": "/sandbox",
            "mounts": [
                {"source": ".adami_data/sandbox_volume", "target": "/sandbox", "mode": "ro"}
            ],
        }
    ]
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_SERVERS_JSON", json.dumps(payload))
    specs = load_mcp_server_specs()
    assert len(specs) == 1
    assert specs[0].name == "demo"


def test_load_mcp_server_specs_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_SERVERS_JSON", "{not-json")
    assert load_mcp_server_specs() == []


def test_load_mcp_server_specs_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_SERVERS_JSON", json.dumps({"name": "x"}))
    assert load_mcp_server_specs() == []


def test_load_mcp_server_specs_missing_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"name": "demo"},  # missing image
        {"image": "x:latest"},  # missing name
    ]
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_SERVERS_JSON", json.dumps(payload))
    assert load_mcp_server_specs() == []


def test_load_mcp_server_specs_duplicate_name_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"name": "demo", "image": "a:latest", "command": ["python", "-c", "print(1)"]},
        {"name": "demo", "image": "b:latest", "command": ["python", "-c", "print(2)"]},
        {"name": "demo2", "image": "c:latest", "command": ["python", "-c", "print(3)"]},
    ]
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_SERVERS_JSON", json.dumps(payload))
    specs = load_mcp_server_specs()
    assert [s.name for s in specs] == ["demo", "demo2"]
