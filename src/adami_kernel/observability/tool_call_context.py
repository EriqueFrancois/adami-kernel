from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_tool_trace_id_ctx: ContextVar[Optional[str]] = ContextVar("tool_trace_id", default=None)


def set_tool_trace_id(trace_id: Optional[str]) -> Token[Optional[str]]:
    return _tool_trace_id_ctx.set(str(trace_id) if trace_id is not None else None)


def reset_tool_trace_id(token: Token[Optional[str]]) -> None:
    _tool_trace_id_ctx.reset(token)


def get_tool_trace_id() -> Optional[str]:
    v = _tool_trace_id_ctx.get(None)
    return str(v) if v is not None else None

