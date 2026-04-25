from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict

TOOLS = [
    {
        "name": "echo",
        "description": "Echo arguments back",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "sleep",
        "description": "Sleep for N seconds",
        "inputSchema": {
            "type": "object",
            "properties": {"sec": {"type": "number"}},
            "required": ["sec"],
        },
    },
]


def _write(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        try:
            if method == "tools/list":
                _write({"jsonrpc": "2.0", "id": rid, "result": TOOLS})
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments") or {}
                if name == "echo":
                    _write({"jsonrpc": "2.0", "id": rid, "result": {"text": args.get("text", "")}})
                elif name == "sleep":
                    sec = float(args.get("sec", 0))
                    time.sleep(sec)
                    _write({"jsonrpc": "2.0", "id": rid, "result": {"slept": sec}})
                else:
                    _write(
                        {"jsonrpc": "2.0", "id": rid, "error": {"message": f"unknown tool: {name}"}}
                    )
            else:
                _write(
                    {"jsonrpc": "2.0", "id": rid, "error": {"message": f"unknown method: {method}"}}
                )
        except Exception as e:
            _write({"jsonrpc": "2.0", "id": rid, "error": {"message": str(e)}})


if __name__ == "__main__":
    main()
