## Purpose

`web/` is the **Web Console backend**. It exposes HTTP/WebSocket interfaces for introspection and operations (e.g., market routes, workflow visibility) and hosts observability hooks.

## Key files

- `app.py`: application entrypoint for the web server (started via `core/boot_manager.py`).
- `market_routes.py`: web routes for skill market / management (uses `app.state` injection).
- `manager.py`: runtime web manager / server coordination.
- `ws.py`: websocket endpoints / streaming utilities.
- `otel.py`: OpenTelemetry bootstrap and bridges.
- `observability.py`: lightweight observability façade used by WorkflowEngine.

## Primary flows

- `BootManager` → `web.app.start_web_console(...)`
- Web routes → read/write state via injected components (`app.state.*`)

