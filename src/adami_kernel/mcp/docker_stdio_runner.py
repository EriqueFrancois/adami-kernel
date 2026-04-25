from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import Any, Dict, Optional

import docker

import adami_kernel.config as config_mod
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.mcp.jsonrpc import JsonRpcRequest, JsonRpcResponse
from adami_kernel.mcp.spec import McpServerSpec

logger = logging.getLogger("AdamI-MCP")


def _mcpdsr_t(key: str, **kwargs) -> str:
    return t(key, locale=config_mod.settings.effective_ui_default_locale(), **kwargs)


@dataclasses.dataclass
class McpStdioHandle:
    """一个运行中的 MCP stdio server 句柄（Docker 容器 + attach socket）。"""

    spec: McpServerSpec
    container_id: str
    sock: Any  # docker API socket wrapper

    async def send(self, req: JsonRpcRequest) -> None:
        await asyncio.to_thread(self.sock._sock.sendall, req.to_line())  # type: ignore[attr-defined]

    async def readline(self) -> bytes:
        buf = b""
        while True:
            payload = await _read_multiplex_payload(self.sock)
            if not payload:
                return buf
            buf += payload
            if b"\n" in buf:
                line, _rest = buf.split(b"\n", 1)
                return line + b"\n"

    async def close(self) -> None:
        try:
            await asyncio.to_thread(self.sock.close)
        except Exception:
            pass


async def _read_exact(sock: Any, n: int) -> bytes:
    out = b""
    while len(out) < n:
        chunk = await asyncio.to_thread(sock._sock.recv, n - len(out))  # type: ignore[attr-defined]
        if not chunk:
            return b""
        out += chunk
    return out


async def _read_multiplex_payload(sock: Any) -> bytes:
    """读取 Docker attach multiplex 的一帧 payload。"""
    header = await _read_exact(sock, 8)
    if not header:
        return b""
    size = int.from_bytes(header[4:8], "big", signed=False)
    if size <= 0:
        return b""
    return await _read_exact(sock, size)


class McpDockerStdioRunner:
    """在 Docker（bridge）中以 stdio 方式运行 MCP server，并做一次请求/响应后退出。

    说明：第一版采用“一次请求一个容器”，避免长期常驻进程复杂度与资源泄露风险。
    """

    def __init__(self) -> None:
        self._client: Optional[docker.DockerClient] = None
        self._req_id = 0

    def _docker(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def start_server(self, spec: McpServerSpec) -> McpStdioHandle:
        """启动 MCP server 容器并返回 stdio 句柄。

        运行参数：
        - network_mode: settings.ADAMI_MCP_DOCKER_NETWORK_MODE（默认 bridge）
        - Dummy Keys：不注入真实密钥
        - 绑定 /sandbox：第一版挂载 sandbox_volume（rw）
        """
        cmd: list[str] = []
        if spec.command:
            cmd.extend(spec.command)
        if spec.args:
            cmd.extend(spec.args)
        if not cmd:
            raise RuntimeError(boot_t("cjk_gate.mcp_missing_command", name=spec.name))

        env = {
            "PYTHONUNBUFFERED": "1",
            "ADAMI_SANDBOX_MODE": "true",
            # Dummy keys：避免 MCP server 读到真实密钥
            "OPENAI_API_KEY": "sk-dummy-key-for-testing-only",
            "KIMI_API_KEY": "sk-dummy-key-for-testing-only",
            "ANTHROPIC_API_KEY": "sk-dummy-key-for-testing-only",
            "DEEPSEEK_API_KEY": "sk-dummy-key-for-testing-only",
            **(spec.env or {}),
        }

        api = self._docker().api
        # 默认不挂载任何宿主路径；仅允许 mounts 中显式声明、且命中 allowlist 的路径
        allowlist = [
            str(x) for x in (config_mod.settings.ADAMI_MCP_MOUNT_ALLOWLIST or []) if str(x).strip()
        ]
        binds: Dict[str, Dict[str, str]] = {}
        if spec.mounts:
            from pathlib import Path

            for m in spec.mounts:
                src = str(Path(m.source).expanduser().resolve())
                if not any(src.startswith(str(Path(p).expanduser().resolve())) for p in allowlist):
                    raise RuntimeError(f"[MCP] mount source not allowed: {src}")
                binds[src] = {"bind": m.target, "mode": m.mode}

        read_only = (
            bool(spec.read_only_fs)
            if spec.read_only_fs is not None
            else bool(getattr(config_mod.settings, "ADAMI_MCP_READ_ONLY_FS", True))
        )
        tmpfs = {"/tmp": "rw,noexec,nosuid,size=64m"} if read_only else None

        host_cfg = api.create_host_config(
            network_mode=config_mod.settings.ADAMI_MCP_DOCKER_NETWORK_MODE,
            binds=(binds if binds else None),
            read_only=read_only,
            tmpfs=tmpfs,
            security_opt=["no-new-privileges:true"],
            mem_limit="512m",
            cpu_quota=50000,
            auto_remove=False,
        )
        cont = api.create_container(
            image=spec.image,
            command=cmd,
            stdin_open=True,
            tty=False,
            environment=env,
            working_dir=spec.workdir or "/",
            host_config=host_cfg,
        )
        container_id = cont.get("Id")
        if not container_id:
            raise RuntimeError("[MCP] create_container failed: missing Id")
        api.start(container_id)

        sock = api.attach_socket(
            container_id,
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "logs": 0},
        )
        return McpStdioHandle(spec=spec, container_id=container_id, sock=sock)

    async def stop_server(self, handle: McpStdioHandle) -> None:
        """退出时 stop/kill + remove，避免容器残留。"""
        try:
            await handle.close()
        finally:
            try:
                api = self._docker().api
                await asyncio.to_thread(api.remove_container, handle.container_id, force=True)
            except Exception:
                pass

    async def request(
        self, spec: McpServerSpec, *, method: str, params: Dict[str, Any]
    ) -> JsonRpcResponse:
        timeout = float(config_mod.settings.ADAMI_MCP_TIMEOUT_SEC)
        rid = self._next_id()
        req = JsonRpcRequest(method=method, params=params, id=rid)

        started = time.time()
        handle: Optional[McpStdioHandle] = None
        try:
            handle = await self.start_server(spec)
            await handle.send(req)
            line = await asyncio.wait_for(handle.readline(), timeout=timeout)
            resp = JsonRpcResponse.from_line(line)
            return resp
        except asyncio.TimeoutError:
            return JsonRpcResponse(id=rid, error={"message": "timeout"})
        except Exception as e:
            logger.warning(_mcpdsr_t("mcpdsr.warn.request", srv=spec.name, meth=method, e=e))
            return JsonRpcResponse(id=rid, error={"message": str(e)})
        finally:
            if handle is not None:
                await self.stop_server(handle)
            elapsed = time.time() - started
            if elapsed > timeout:
                logger.debug(_mcpdsr_t("mcpdsr.debug.elapsed", elapsed=elapsed, tmo=timeout))

    # 兼容旧实现：保留内部方法签名不再使用（避免外部 import 断裂）
    async def _readline(self, sock: Any) -> bytes:  # pragma: no cover
        h = McpStdioHandle(
            spec=McpServerSpec(name="tmp", image="tmp", command=[]), container_id="tmp", sock=sock
        )
        return await h.readline()

    async def _read_multiplex_payload(self, sock: Any) -> bytes:  # pragma: no cover
        return await _read_multiplex_payload(sock)

    async def _read_exact(self, sock: Any, n: int) -> bytes:  # pragma: no cover
        return await _read_exact(sock, n)
