from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from adami_kernel.mcp.jsonrpc import JsonRpcRequest, JsonRpcResponse

logger = logging.getLogger("AdamI-MCP")

SendFn = Callable[[bytes], Awaitable[None]]
RecvLineFn = Callable[[], Awaitable[bytes]]


class JsonRpcStdioClient:
    """最小 JSON-RPC 客户端（基于 stdio 的“按行”协议）。

    设计目标：
    - 不绑定任何 transport：只依赖 send(bytes) 与 recv_line()->bytes
    - 单请求单响应（最小闭环，足够 tools/list 与 tools/call）
    - 超时可控，不挂死 event loop
    """

    def __init__(self, *, send: SendFn, recv_line: RecvLineFn) -> None:
        self._send = send
        self._recv_line = recv_line
        self._id = 0
        self._lock = asyncio.Lock()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def request(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0
    ) -> JsonRpcResponse:
        rid = self._next_id()
        req = JsonRpcRequest(method=method, params=params or {}, id=rid)

        async with self._lock:
            try:
                await self._send(req.to_line())
                line = await asyncio.wait_for(self._recv_line(), timeout=timeout)
                if not line:
                    return JsonRpcResponse(id=rid, error={"message": "empty response"})
                return JsonRpcResponse.from_line(line)
            except asyncio.TimeoutError:
                return JsonRpcResponse(id=rid, error={"message": "timeout"})
            except Exception as e:
                logger.warning("[MCP][JSONRPC] request failed method=%s err=%s", method, e)
                return JsonRpcResponse(id=rid, error={"message": str(e)})

    async def tools_list(self, timeout: float = 30.0) -> JsonRpcResponse:
        return await self.request("tools/list", {}, timeout=timeout)

    async def tools_call(
        self, *, name: str, arguments: Dict[str, Any], timeout: float = 30.0
    ) -> JsonRpcResponse:
        return await self.request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=timeout
        )
