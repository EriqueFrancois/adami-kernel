## Purpose

`nexus/` is the **communications spine** of the kernel:

- event primitives (`AdamiEvent`)
- the publish/subscribe bus
- nerves and sensory adapters (Telegram/Discord)
- the interactive CLI shell

## Key files

- `bus.py`: EventBus pub/sub.
- `event.py`: `AdamiEvent` model and priority.
- `shell.py`: `InteractiveShell` (CLI loop that publishes `system.events`).
- `sensory.py`: sensory coordination.
- `telegram_sensory.py`, `discord_nerve.py`: platform integrations.
- `dlq.py`: dead-letter queue support.
- `health_server.py`: health endpoints / liveness.

## Primary flows

- **CLI**
  - `shell.py` reads stdin → publishes `system.events` with `chat_id="cli"`.

- **External nerves**
  - Telegram/Discord adapters → publish into `system.events`.

