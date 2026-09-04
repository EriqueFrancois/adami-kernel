"""SSE framing helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def format_sse(event: str, payload: Mapping[str, Any]) -> bytes:
    data = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def chunk_text(text: str, size: int = 48) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]
