# AdamI — API reference (engineering)

**Audience**: integrators embedding AdamI, internal platform teams.

This is a **hand-curated** reference aligned to the current tree. It is **not** auto-generated from docstrings for every symbol; for exhaustive symbols use IDE + `pyright` (`pyproject.toml` strict mode).

---

## 1. Core event model

### `adami_kernel.nexus.event.AdamiEvent` (`pydantic.BaseModel`)

| Field | Type | Description |
|-------|------|-------------|
| `trace_id` | `str` | Correlation id (adapters often use timestamps or counters). |
| `source_module` | `str` | Producer label (e.g. `user.prompt`, `sensory.telegram`). |
| `target_topic` | `str` | Pub/sub topic (e.g. `system.events`). |
| `priority` | `EventPriority` | Enum: `LOW`, `NORMAL`, `HIGH`, `URGENT`. |
| `payload` | `Dict[str, Any]` | **Extensible** per adapter; always treated as mutable by middleware. |

`EventPriority` is defined in the same module.

---

## 2. Event bus

### `adami_kernel.nexus.bus.EventBus`

| Method | Signature (conceptual) | Returns | Notes |
|--------|------------------------|---------|-------|
| `subscribe` | `async def subscribe(self, topic: str) -> asyncio.Queue` | `asyncio.Queue` | Each subscriber gets its own queue instance. |
| `publish` | `async def publish(self, event: Any) -> bool` | `bool` | `True` if at least one queue accepted the event; `False` if blocked, no subscribers, RBAC deny, or queue timeout (may push DLQ when configured). |
| `add_middleware` | `def add_middleware(self, middleware: Callable[[Any], Awaitable[bool]])` | `None` | Middleware must return `True` to continue publishing. |
| `initialize` | `async def initialize(self)` | `None` | Attaches `SensitiveFilter` + trace sink middleware; starts DLQ replay task. |

**Topics** (see also `ARCHITECTURE.md`): `system.events`, `workflow.events`, `hitl.events`, `agent.communication`, …

---

## 3. Sensory base — creating events

### `adami_kernel.nexus.base_nerve.BaseNerve`

Integrators subclass or compose via existing nerves.

| Method | Description |
|--------|-------------|
| `create_event(task: str, platform: str = "base", priority: EventPriority = HIGH, **payload_extra) -> AdamiEvent` | Builds `AdamiEvent` with `target_topic="system.events"` and default `chat_id` from `last_chat_id` unless overridden in `payload_extra`. |
| `publish(event: AdamiEvent) -> Awaitable[None]` | Injected at construction (`publish_func`); implementation is wired to `EventBus.publish` in boot. |

**Common `payload_extra` keys** (observed across nerves; not guaranteed universal):

- `chat_id: str` — session / channel discriminator.
- `raw_content: str` — original user text.
- `locale: str` — BCP-47 hint for i18n resolution.
- `platform: str` — duplicated inside payload for downstream processors.
- Discord-specific: `discord_channel_id`, `discord_author`, `is_dm`.
- Media: `media_type`, `image_base64`, etc.

---

## 4. Lifecycle façade (integration surface)

`adami_kernel.core.lifecycle_manager.LifecycleManager` is the **runtime kernel object** passed to `InteractiveShell` and consumed by `DecisionProcessor` as `KernelContext`.

Important **proxied** capabilities (non-exhaustive):

- `_send_reply(chat_id, text, platform)`
- `persist_chat_locale_override(chat_id, locale)`
- `request_process_restart()` — cooperative shutdown + `execv` path (see `SECURITY.md` / ops notes).

---

## 5. CLI / ports (user commands)

| Surface | Mechanism |
|---------|-----------|
| CLI menu | `InteractiveShell` (`shell.py`) |
| Telegram / Discord | Entry menus + `AdamiEvent` publish |

Slash-style commands inside user text (e.g. `/report run daily`) are interpreted by `DecisionProcessor` after intent routing — treat them as **plain task strings** in events.

---

## 6. Tooling expectations

- **Type checking**: `poetry run pyright` (strict).
- **Lint**: `poetry run ruff check src/ tests/`.
- **Tests**: `poetry run pytest -m "not integration and not stress"`.

---

## 7. Versioning

`pyproject.toml` carries package version (`0.1.0` at time of writing). Public JSON/i18n catalogs are **not** semver-guarded separately — treat catalog key additions as contract changes for your fork.
