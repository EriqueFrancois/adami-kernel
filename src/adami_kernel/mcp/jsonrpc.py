from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class JsonRpcRequest:
    method: str
    params: Dict[str, Any]
    id: int

    def to_line(self) -> bytes:
        return (
            json.dumps(
                {"jsonrpc": "2.0", "id": self.id, "method": self.method, "params": self.params}
            )
            + "\n"
        ).encode("utf-8")


@dataclass
class JsonRpcResponse:
    id: Optional[int]
    result: Any = None
    error: Optional[dict] = None

    @classmethod
    def from_line(cls, line: bytes) -> "JsonRpcResponse":
        obj = json.loads(line.decode("utf-8", errors="ignore"))
        return cls(id=obj.get("id"), result=obj.get("result"), error=obj.get("error"))
