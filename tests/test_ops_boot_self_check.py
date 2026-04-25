from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.config import Settings
from adami_kernel.ops.boot_self_check import (
    BootSelfCheckReport,
    collect_warnings,
    run_boot_self_check,
)
from adami_kernel.ops.ops_boot_self_check_cli import main as cli_main


def _clear_messenger_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "DISCORD_BOT_TOKEN",
        "DISCORD_DEFAULT_USER_ID",
        "DISCORD_DEFAULT_CHANNEL_ID",
        "DISCORD_DEFAULT_GUILD_ID",
        "DISCORD_SLASH_GUILD_ID",
    ):
        monkeypatch.delenv(k, raising=False)


def test_collect_warnings_production_plus_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_messenger_env(monkeypatch)
    monkeypatch.setenv("ADAMI_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("DEBUG", "true")
    s = Settings(_env_file=())
    w = collect_warnings(s, docker_reachable=True)
    assert any("DEBUG=true" in x for x in w)


def test_collect_warnings_mcp_no_allow_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_messenger_env(monkeypatch)
    monkeypatch.setenv("ADAMI_MCP_ENABLED", "true")
    monkeypatch.delenv("ADAMI_MCP_ALLOW_TOOLS", raising=False)
    monkeypatch.delenv("ADAMI_MCP_DENY_TOOLS", raising=False)
    s = Settings(_env_file=())
    w = collect_warnings(s, docker_reachable=True)
    assert any("ADAMI_MCP_ALLOW_TOOLS" in x and "threat" in x for x in w)


def test_run_boot_self_check_returns_dataclass(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_messenger_env(monkeypatch)
    s = Settings(_env_file=())
    r = run_boot_self_check(s)
    assert isinstance(r, BootSelfCheckReport)
    assert isinstance(r.modules_enabled, list)
    assert "WorkflowEngine" in r.modules_enabled
    d = r.to_json_dict()
    assert d["runtime_profile"] in ("development", "production")
    json.dumps(d)


def test_cli_json_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_messenger_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("# isolated — no messenger tokens\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["adami-ops-boot-check", "--json"])
    code = cli_main()
    assert code in (0, 1, 2)
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert "modules_enabled" in data
    assert "warnings" in data


def test_cli_exit_warn_when_sim_webhook_no_secret(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_messenger_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "ADAMI_SIM_WEBHOOK_ENABLED=true\n",
        encoding="utf-8",
    )
    # ``Settings`` env_file tuple is fixed at import time; ignore nerve noise for exit-code focus.
    monkeypatch.setattr(
        "adami_kernel.ops.boot_self_check._nerve_preflight_warnings",
        lambda: [],
    )
    monkeypatch.setattr("sys.argv", ["adami-ops-boot-check"])
    code = cli_main()
    out = capsys.readouterr().out
    assert "WEBHOOK_SECRET" in out
    assert code == 1
