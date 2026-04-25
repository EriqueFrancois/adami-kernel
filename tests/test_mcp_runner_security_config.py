from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import adami_kernel.config as config_mod
from adami_kernel.mcp.docker_stdio_runner import McpDockerStdioRunner
from adami_kernel.mcp.spec import McpServerSpec


class _FakeApi:
    def __init__(self) -> None:
        self.last_host_cfg = None
        self.last_container = None

    def create_host_config(self, **kwargs):
        self.last_host_cfg = kwargs
        return kwargs

    def create_container(self, **kwargs):
        self.last_container = kwargs
        return {"Id": "cid"}

    def start(self, _cid):  # noqa: ANN001
        return None

    def attach_socket(self, _cid, params):  # noqa: ANN001
        # minimal stub with required attributes
        return SimpleNamespace(
            _sock=SimpleNamespace(sendall=lambda _b: None, recv=lambda _n: b""), close=lambda: None
        )


class _FakeDocker:
    def __init__(self, api):
        self.api = api


def test_runner_default_no_mounts_readonly_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_api = _FakeApi()
    runner = McpDockerStdioRunner()
    monkeypatch.setattr(runner, "_docker", lambda: _FakeDocker(fake_api))
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DOCKER_NETWORK_MODE", "bridge")
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_READ_ONLY_FS", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_MOUNT_ALLOWLIST", [])

    spec = McpServerSpec(name="x", image="img", command=["python", "-c", "print(1)"])

    async def run():
        h = await runner.start_server(spec)
        await runner.stop_server(h)

    asyncio.run(run())
    assert fake_api.last_host_cfg["network_mode"] == "bridge"
    assert fake_api.last_host_cfg["binds"] is None
    assert fake_api.last_host_cfg["read_only"] is True
    assert "/tmp" in (fake_api.last_host_cfg.get("tmpfs") or {})


def test_runner_mount_not_in_allowlist_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_api = _FakeApi()
    runner = McpDockerStdioRunner()
    monkeypatch.setattr(runner, "_docker", lambda: _FakeDocker(fake_api))
    monkeypatch.setattr(
        config_mod.settings, "ADAMI_MCP_MOUNT_ALLOWLIST", [".adami_data/sandbox_volume"]
    )

    spec = McpServerSpec(
        name="x",
        image="img",
        command=["python"],
        mounts=[{"source": ".env", "target": "/secrets", "mode": "ro"}],
    )

    async def run():
        await runner.start_server(spec)

    with pytest.raises(RuntimeError):
        asyncio.run(run())
