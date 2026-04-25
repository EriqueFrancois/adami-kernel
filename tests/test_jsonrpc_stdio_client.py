from __future__ import annotations

import asyncio
import json
from typing import List

from adami_kernel.mcp.jsonrpc_stdio_client import JsonRpcStdioClient


def test_request_response_parsing_and_id_increments() -> None:
    writes: List[bytes] = []

    async def send(b: bytes) -> None:
        writes.append(b)

    async def recv_line() -> bytes:
        return (json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}) + "\n").encode(
            "utf-8"
        )

    async def run() -> None:
        c = JsonRpcStdioClient(send=send, recv_line=recv_line)
        r1 = await c.request("tools/list", {}, timeout=0.5)
        assert r1.error is None
        assert r1.result == {"ok": True}
        assert len(writes) == 1
        sent = json.loads(writes[0].decode("utf-8"))
        assert sent["id"] == 1
        assert sent["method"] == "tools/list"

        # second request id increments
        async def recv_line2() -> bytes:
            return (json.dumps({"jsonrpc": "2.0", "id": 2, "result": 123}) + "\n").encode("utf-8")

        c2 = JsonRpcStdioClient(send=send, recv_line=recv_line2)
        r2 = await c2.request("x", {}, timeout=0.5)
        assert r2.result == 123

    asyncio.run(run())


def test_timeout_is_controlled_error() -> None:
    async def send(_b: bytes) -> None:
        return None

    async def recv_line() -> bytes:
        await asyncio.sleep(10)
        return b""

    async def run() -> None:
        c = JsonRpcStdioClient(send=send, recv_line=recv_line)
        r = await c.request("tools/list", {}, timeout=0.05)
        assert r.error is not None
        assert r.error.get("message") == "timeout"

    asyncio.run(run())
