from __future__ import annotations

import asyncio
import json
import os
import logging

from adami_kernel.config import reload_settings, settings
from adami_kernel.mcp.docker_stdio_runner import McpDockerStdioRunner
from adami_kernel.mcp.spec import McpServerSpec
from adami_kernel.mcp.manager import McpManager


class FakeEvolution:
    """最小替身：避免引入完整依赖（aiosqlite 等）。"""

    def __init__(self) -> None:
        self.tool_schemas = {}
        self.dynamic_skills = {}

    def register_tool(self, name: str, json_schema: dict, description: str = "") -> None:
        name = str(name).upper()
        self.tool_schemas[name] = {"json_schema": json_schema, "description": description}


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # 1) 通过环境变量覆盖 settings（避免改动仓库配置）
    os.environ["ADAMI_MCP_ENABLED"] = "true"
    os.environ["ADAMI_MCP_TIMEOUT_SEC"] = "20"
    os.environ["ADAMI_MCP_DOCKER_NETWORK_MODE"] = "bridge"

    # server 指向 python 官方镜像，运行 /sandbox/mcp_dummy_server.py
    servers = [
        {
            "name": "dummy",
            "image": "python:3.13-slim",
            "command": ["python", "/sandbox/mcp_dummy_server.py"],
            "args": [],
            "env": {},
            "workdir": "/sandbox",
            "mounts": [{"source": ".adami_data/sandbox_volume", "target": "/sandbox", "mode": "ro"}],
        }
    ]
    os.environ["ADAMI_MCP_SERVERS_JSON"] = json.dumps(servers, ensure_ascii=False)
    # 允许挂载 sandbox_volume（仅用于验收 dummy server）
    os.environ["ADAMI_MCP_MOUNT_ALLOWLIST"] = json.dumps([".adami_data/sandbox_volume"])

    # 默认拒绝验证：allow 为空 → 不应注册任何 MCP 工具
    os.environ["ADAMI_MCP_ALLOW_TOOLS"] = "[]"
    os.environ["ADAMI_MCP_DENY_TOOLS"] = "[]"
    reload_settings()
    print("debug_enabled_1:", __import__("adami_kernel.config").config.settings.ADAMI_MCP_ENABLED)

    evo = FakeEvolution()
    mgr = McpManager(evolution_engine=evo)
    await mgr.initialize()
    mcp_tools = [k for k in evo.tool_schemas.keys() if k.startswith("MCP.")]
    print("case_default_deny_registered:", len(mcp_tools))

    # 2) allow echo → 应注册 MCP.DUMMY.ECHO 并可调用
    os.environ["ADAMI_MCP_ALLOW_TOOLS"] = json.dumps(["echo"])
    reload_settings()
    print("debug_enabled_2:", __import__("adami_kernel.config").config.settings.ADAMI_MCP_ENABLED)
    print("debug_allow_2:", __import__("adami_kernel.config").config.settings.ADAMI_MCP_ALLOW_TOOLS)

    # runner 直连 debug：确认 tools/list 实际返回
    spec = McpServerSpec.model_validate(servers[0])
    runner = McpDockerStdioRunner()
    resp = await runner.request(spec, method="tools/list", params={})
    print("debug_tools_list_resp:", {"id": resp.id, "error": resp.error, "result": resp.result})

    evo2 = FakeEvolution()
    mgr2 = McpManager(evolution_engine=evo2)
    await mgr2.initialize()

    key = "MCP.DUMMY.ECHO"
    print(
        "case_allow_registered:",
        key in evo2.tool_schemas,
        "total_mcp=",
        len([k for k in evo2.tool_schemas if k.startswith("MCP.")]),
    )

    fn = evo2.dynamic_skills.get(key)
    if fn is None:
        raise RuntimeError("dynamic_skills missing")
    out = await fn(text="hello")
    print("case_call_result:", out)

    # 3) server 崩溃/不可用 → initialize 不应抛致命异常（已在 manager 内 warning+continue）
    os.environ["ADAMI_MCP_SERVERS_JSON"] = json.dumps(
        [
            {
                "name": "bad",
                "image": "python:3.13-slim",
                "command": ["python", "/sandbox/no_such_file.py"],
            }
        ],
        ensure_ascii=False,
    )
    os.environ["ADAMI_MCP_ALLOW_TOOLS"] = json.dumps(["echo"])
    reload_settings()
    evo3 = FakeEvolution()
    mgr3 = McpManager(evolution_engine=evo3)
    await mgr3.initialize()
    print("case_server_crash_registered:", len([k for k in evo3.tool_schemas if k.startswith("MCP.")]))

    print("OK")


if __name__ == "__main__":
    asyncio.run(main())

