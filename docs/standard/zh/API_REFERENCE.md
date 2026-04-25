# AdamI — API 参考（工程向）

**读者**：系统集成方、内部平台团队。

本文为与当前代码树对齐的**手工维护**索引；**并非**全量从 docstring 自动生成。穷尽符号请用 IDE + `pyright`（`pyproject.toml` 为 strict）。

---

## 1. 核心事件模型

### `adami_kernel.nexus.event.AdamiEvent`（`pydantic.BaseModel`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `trace_id` | `str` | 关联 ID（适配器常用时间戳或计数器）。 |
| `source_module` | `str` | 生产者标签（如 `user.prompt`、`sensory.telegram`）。 |
| `target_topic` | `str` | 发布订阅主题（如 `system.events`）。 |
| `priority` | `EventPriority` | 枚举：`LOW`、`NORMAL`、`HIGH`、`URGENT`。 |
| `payload` | `Dict[str, Any]` | **可扩展**；中间件可能就地改写。 |

`EventPriority` 与同模块定义。

---

## 2. 事件总线

### `adami_kernel.nexus.bus.EventBus`

| 方法 | 概念签名 | 返回 | 说明 |
|------|----------|------|------|
| `subscribe` | `async def subscribe(self, topic: str) -> asyncio.Queue` | `asyncio.Queue` | 每个订阅方独立队列。 |
| `publish` | `async def publish(self, event: Any) -> bool` | `bool` | 至少一个订阅队列成功 `put` 为 `True`；若中间件拦截、无订阅者、RBAC 拒绝或队列超时则可能为 `False`（配置 DLQ 时可能入队）。 |
| `add_middleware` | `def add_middleware(self, middleware: Callable[[Any], Awaitable[bool]])` | `None` | 中间件返回 `True` 方可继续发布链。 |
| `initialize` | `async def initialize(self)` | `None` | 挂载 `SensitiveFilter` 与 trace sink；启动 DLQ 回放任务。 |

**主题（Topic）**：亦见 [ARCHITECTURE.md](ARCHITECTURE.md)：`system.events`、`workflow.events`、`hitl.events`、`agent.communication` 等。

---

## 3. 感官基类 — 构造事件

### `adami_kernel.nexus.base_nerve.BaseNerve`

| 方法 | 说明 |
|------|------|
| `create_event(task: str, platform: str = "base", priority: EventPriority = HIGH, **payload_extra) -> AdamiEvent` | 生成 `target_topic="system.events"` 的 `AdamiEvent`；若未在 `payload_extra` 覆盖 `chat_id`，则使用 `last_chat_id`。 |
| `publish(event: AdamiEvent)` | 构造时注入的异步函数，引导期绑定到 `EventBus.publish`。 |

**常见 `payload_extra` 键**（各 Nerve 可见；非全仓库保证）：

- `chat_id: str`
- `raw_content: str`
- `locale: str` — BCP-47 提示
- `platform: str`
- Discord：`discord_channel_id`、`discord_author`、`is_dm`
- 媒体：`media_type`、`image_base64` 等

---

## 4. 生命周期门面（集成面）

`adami_kernel.core.lifecycle_manager.LifecycleManager` 为传入 `InteractiveShell`、并被 `DecisionProcessor` 作为 `KernelContext` 使用的**运行时内核对象**。

部分代理能力（非穷尽）：

- `_send_reply(chat_id, text, platform)`
- `persist_chat_locale_override(chat_id, locale)`
- `request_process_restart()` — 协作式关闭与进程替换路径（运维与安全见 [SECURITY.md](SECURITY.md)）。

---

## 5. CLI / 端口（用户命令）

| 表面 | 机制 |
|------|------|
| CLI 菜单 | `InteractiveShell`（`shell.py`） |
| Telegram / Discord | 入口菜单 + `AdamiEvent.publish` |

用户文本内的类命令串（如 `/report run daily`）经意图路由后由 `DecisionProcessor` 解释 —— 在事件中仍表现为**普通 task 字符串**。

---

## 6. 工具链期望

- **类型检查**：`poetry run pyright`（strict）。
- **Lint**：`poetry run ruff check src/ tests/`。
- **测试**：`poetry run pytest -m "not integration and not stress"`。

---

## 7. 版本化

`pyproject.toml` 中 `version` 为包版本（撰写时为 `0.1.0`）。公开 JSON/i18n 目录**未**单独 semver —— 若 fork 维护，请将 catalog 键增删视为契约变更。
