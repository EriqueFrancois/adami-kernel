from __future__ import annotations

import json
from pathlib import Path

import pytest

import adami_kernel.config as config_mod
from adami_kernel.nexus import chat_settings_wizard as chat_wiz
from adami_kernel.nexus.cli_settings_wizard import (
    _category_id_for_field,
    _fields_by_category,
    mcp_servers_json_template,
    write_cli_overrides,
)


def test_mcp_fields_are_categorized() -> None:
    assert _category_id_for_field("ADAMI_MCP_ENABLED") == "mcp"
    assert _category_id_for_field("ADAMI_MCP_SERVERS_JSON") == "mcp"
    assert _category_id_for_field("ADAMI_MCP_MODULE_AGENT_ENABLED") == "mcp"
    assert _category_id_for_field("ADAMI_USE_MCP_AGENT") == "mcp"
    assert _category_id_for_field("ADAMI_USE_MCP_AGENT_PLANNER") == "mcp"
    by = _fields_by_category()
    assert "ADAMI_MCP_SERVERS_JSON" in by.get("mcp", [])
    assert "ADAMI_USE_MCP_AGENT" in by.get("mcp", [])


def test_sim_fields_are_categorized() -> None:
    assert _category_id_for_field("ADAMI_SIM_MODULE_ENABLED") == "sim"
    assert _category_id_for_field("ADAMI_SIM_TRACE_EXPORT_ENABLED") == "sim"
    assert _category_id_for_field("ADAMI_SIM_WEBHOOK_ENABLED") == "sim"
    by = _fields_by_category()
    assert "ADAMI_SIM_TRACE_EXPORT_ENABLED" in by.get("sim", [])


def test_mcp_servers_json_template_is_valid_json() -> None:
    tpl = mcp_servers_json_template()
    data = json.loads(tpl)
    assert isinstance(data, list) and data
    s0 = data[0]
    for k in ["name", "image", "command", "args", "env", "workdir"]:
        assert k in s0
    assert isinstance(s0["command"], list)


def test_chat_tpl_returns_template() -> None:
    st = chat_wiz.ChatSettingsState(
        stage="value", category_id="mcp", field_name="ADAMI_MCP_SERVERS_JSON"
    )
    st2, msg, _btn = chat_wiz.handle_text(st, "tpl")
    assert st2.stage == "value"
    assert "ADAMI_MCP_SERVERS_JSON" in msg
    # 能被 JSON 解析
    start = msg.split("：\n", 1)[-1]
    json.loads(start)


def test_cli_overrides_can_save_and_reload_mcp_servers_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / "cli_overrides.env"
    monkeypatch.setenv("ADAMI_CLI_ENV_FILE", str(env_path))

    payload = [
        {
            "name": "dummy",
            "image": "python:3.13-slim",
            "command": ["python", "/sandbox/mcp_dummy_server.py"],
            "args": [],
            "env": {},
            "workdir": "/sandbox",
        }
    ]
    write_cli_overrides({"ADAMI_MCP_SERVERS_JSON": json.dumps(payload, ensure_ascii=False)})

    config_mod.reload_settings()
    assert config_mod.settings.ADAMI_MCP_SERVERS_JSON is not None
    assert json.loads(config_mod.settings.ADAMI_MCP_SERVERS_JSON)[0]["name"] == "dummy"
