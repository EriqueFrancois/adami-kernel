from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import adami_kernel.config as config_mod
from adami_kernel.mcp.docker_stdio_runner import McpDockerStdioRunner
from adami_kernel.mcp.spec import McpServerSpec

pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        import docker  # type: ignore

        docker.from_env().ping()
        return True
    except Exception:
        return False


def test_docker_stdio_tools_list_and_call() -> None:
    if not _docker_available():
        pytest.skip("docker not available")

    # allowlist mounts: tests/mcp_dummy_server -> /sandbox
    dummy_dir = str((Path(__file__).parent / "mcp_dummy_server").resolve())
    config_mod.settings.ADAMI_MCP_MOUNT_ALLOWLIST = [dummy_dir]
    config_mod.settings.ADAMI_MCP_READ_ONLY_FS = True
    config_mod.settings.ADAMI_MCP_DOCKER_NETWORK_MODE = "bridge"
    config_mod.settings.ADAMI_MCP_TIMEOUT_SEC = 10.0

    spec = McpServerSpec(
        name="dummy",
        image="python:3.13-slim",
        command=["python", "/sandbox/mcp_dummy_server.py"],
        workdir="/sandbox",
        mounts=[{"source": dummy_dir, "target": "/sandbox", "mode": "ro"}],
    )

    runner = McpDockerStdioRunner()

    async def run() -> None:
        r1 = await runner.request(spec, method="tools/list", params={})
        assert r1.error is None
        assert isinstance(r1.result, list)
        names = {t.get("name") for t in r1.result}
        assert "echo" in names

        r2 = await runner.request(
            spec, method="tools/call", params={"name": "echo", "arguments": {"text": "hello"}}
        )
        assert r2.error is None
        assert r2.result == {"text": "hello"}

    asyncio.run(run())


def test_docker_stdio_timeout_is_controlled() -> None:
    if not _docker_available():
        pytest.skip("docker not available")

    dummy_dir = str((Path(__file__).parent / "mcp_dummy_server").resolve())
    config_mod.settings.ADAMI_MCP_MOUNT_ALLOWLIST = [dummy_dir]
    config_mod.settings.ADAMI_MCP_READ_ONLY_FS = True
    config_mod.settings.ADAMI_MCP_DOCKER_NETWORK_MODE = "bridge"
    config_mod.settings.ADAMI_MCP_TIMEOUT_SEC = 0.2

    spec = McpServerSpec(
        name="dummy",
        image="python:3.13-slim",
        command=["python", "/sandbox/mcp_dummy_server.py"],
        workdir="/sandbox",
        mounts=[{"source": dummy_dir, "target": "/sandbox", "mode": "ro"}],
    )

    runner = McpDockerStdioRunner()

    async def run() -> None:
        r = await runner.request(
            spec, method="tools/call", params={"name": "sleep", "arguments": {"sec": 1.0}}
        )
        assert r.error is not None
        assert r.error.get("message") == "timeout"

    asyncio.run(run())
