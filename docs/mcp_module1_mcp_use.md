# 第一模块 — 原生 MCP（Docker stdio）与 mcp-use 生态

短文档：说明 AdamI **第一模块**（自研 MCP 接入）的能力边界，以及与上游 **[mcp-use/mcp-use](https://github.com/mcp-use/mcp-use)**（Python MCP 客户端 / 工具链套件）的关系。

## 0. 范围冻结

| 项 | 约定 |
|----|------|
| **本仓库「第一模块」** | `McpManager` + `McpDockerStdioRunner` + `tool_adapter`（allow/deny）+ `ADAMI_MCP_*` 配置；**不**依赖 PyPI 包 `mcp-use` |
| **mcp-use（上游）** | 独立开源项目：多传输、Agent 侧连接 MCP Server 的客户端库与工具链；AdamI 当前 **未**将其作为运行时依赖嵌入内核 |
| **对齐点** | 双方均面向 **MCP 协议**（工具发现、`tools/list`、`tools/call`）；AdamI 通过 **Docker 隔离 stdio** 起停 Server 容器，安全策略见 `docker_stdio_runner` 与 `ADAMI_MCP_MOUNT_ALLOWLIST` |

### 何时参考 mcp-use

- 需要 **非 Docker** 传输（本地 stdio 子进程、HTTP/SSE 等）或与其示例 Server 互通时，可在 **进程外** 用 mcp-use 做探测；接入 AdamI 生产路径仍推荐走 **`ADAMI_MCP_SERVERS_JSON`** 与第一模块 runner，以保持挂载白名单与只读 rootfs 一致。

## 1. AdamI 第一模块概念映射

| 能力 | AdamI 实现 | 备注 |
|------|------------|------|
| Server 描述 | `ADAMI_MCP_SERVERS_JSON`（数组：name、image、command、env、mounts…） | 与第二模块 `mcp_agent_config` **同源映射** |
| 传输 | Docker 容器 stdio | `network_mode`、`read_only`、超时见 `ADAMI_MCP_*` |
| 工具注册 | `McpManager` → `dynamic_skills` / 契约层 | 需 `ADAMI_MCP_ENABLED=true` |
| 暴露控制 | `ADAMI_MCP_ALLOW_TOOLS` / `ADAMI_MCP_DENY_TOOLS` | 空 allow = 默认拒绝 |

## 2. 配置一览（`config.py` / 环境变量）

| 变量 | 含义 |
|------|------|
| `ADAMI_MCP_ENABLED` | 是否加载 MCP、注册工具 |
| `ADAMI_MCP_SERVERS_JSON` | Server 列表 JSON |
| `ADAMI_MCP_ALLOW_TOOLS` / `ADAMI_MCP_DENY_TOOLS` | 白名单 / 黑名单 |
| `ADAMI_MCP_DOCKER_NETWORK_MODE` | 容器网络（默认 `bridge`，禁止 `host`） |
| `ADAMI_MCP_TIMEOUT_SEC` | 调用超时 |
| `ADAMI_MCP_READ_ONLY_FS` | 容器 rootfs 只读（推荐 true） |
| `ADAMI_MCP_MOUNT_ALLOWLIST` | 宿主挂载前缀白名单 |

CLI / 聊天「系统设置」中上述字段归类为 **「MCP（外部工具接入…）」**。

## 相关路径

- Sim 画布经 MCP 调 AdamI（模块三）：`docs/sim_mcp_bridge.md`
- 实现：`src/adami_kernel/mcp/`
- 契约与 LLM 可见性：`src/adami_kernel/integration/mcp_agent/contracts.py`
- 第二模块（mcp-agent）说明：`docs/mcp_module2_lastmile_mcp_agent.md`
- 双栈迁移策略（后期）：`docs/mcp_agent_step7_migration.md`
