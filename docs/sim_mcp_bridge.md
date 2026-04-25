# Sim × AdamI — MCP 互操作（步骤 4）

本文固定 **模块三（Sim）** 与 **模块一（原生 MCP）**、**模块二（mcp-agent）** 在 **MCP 协议层**的协同方式，避免双栈重复封装与安全模型漂移。实现落地分路径 A / B，可并行演进。

**官方参考**

- Sim MCP：<https://docs.sim.ai/mcp>
- AdamI 模块一：`docs/mcp_module1_mcp_use.md`
- AdamI 模块二：`docs/mcp_module2_lastmile_mcp_agent.md`
- 契约层：`src/adami_kernel/integration/mcp_agent/contracts.py`

---

## 路径 A — AdamI 暴露 MCP Server，供 Sim 画布调用

**意图**：Sim 作为 **MCP Client**，通过 MCP 连接 **AdamI 提供的 Server**，在画布块中调用已对齐 `tool_id` / schema 的能力（与 `McpManager` 注册表、allow/deny 策略一致）。

**技术要点**

1. **传输**：优先 **stdio** 或 **Streamable HTTP**（以 Sim 与所选 MCP SDK 支持的传输为准）；AdamI 侧需独立 **MCP Server 进程**（或同机子进程），**不**与内核主循环抢同一个 EventLoop（推荐进程隔离）。
2. **工具语义**：对外 `tools/list` / `tools/call` 的 **名称与 JSON Schema** 应与 `ToolContractRegistry` / `get_registered_tools_for_llm` 可见集合对齐（或显式前缀 `adami.*`，并在文档中映射）。
3. **安全**：与第一模块一致——**默认拒绝**；仅暴露 `ADAMI_MCP_ALLOW_TOOLS` 允许的 tool；敏感路径走现有 `tool_adapter` / 脱敏；**禁止**在 Server 内绕过 Docker 策略去执行未白名单的宿主命令。
4. **与模块二**：若 Sim 侧同时连「AdamI MCP Server」与「其他 MCP Server」，AdamI 内核内 **Planner** 仍可通过 `ADAMI_USE_MCP_AGENT` 走 mcp-agent 执行路径；二者关系为 **不同 Client 视角**，需在运维上避免同一 `tool_id` 歧义（命名空间前缀）。

**落地顺序（建议）**

1. 最小 Server：`tools/list` 返回 1 个只读探针 tool（如 `adami.health.ping`）。  
2. 将 1 个只读业务 tool 映射到现有 `ToolboxManager` / 契约调用。  
3. 再扩展列表与鉴权（API Key / mTLS 由网关或 MCP 传输层承担）。

**代码锚点（AdamI 侧）**

- 工具注册与执行：`McpManager`、`EvolutionEngine.execute_tool_dispatch`、`integration/mcp_agent/tool_executor.py`
- Docker 与 argv：`integration/mcp_agent/mcp_agent_config.py`

---

## 路径 B — Sim 侧 MCP 连外部服务；AdamI 提供 HTTP 工具适配

**意图**：Sim 工作流通过 **HTTP / Function 块** 调用 AdamI 暴露的 **受控 HTTP API**（非 MCP 传输），由 AdamI 网关将请求转为内部 `ToolInvocation` 或固定技能入口。

**技术要点**

1. **边界**：HTTP 层只做 **认证、限流、请求体大小限制**；业务仍落内核既有 **RBAC / allowlist**（与路径 A 同一套策略源，避免双份配置）。
2. **与路径 A 差异**：路径 B **不**要求 Sim 支持 MCP Client 连 AdamI；适合 Sim 仅开放 REST/Webhook 的场景。
3. **风险**：HTTP 面更易被扫；默认应 **关闭** 或仅绑定内网 + 强鉴权。

**落地顺序（建议）**

1. 单一 `POST /internal/sim-bridge/tool-call`（示例路径），body 含 `tool_id` + `args`（JSON），响应为结构化 JSON。  
2. 与 `contracts.ToolInvocation` 对齐校验；拒绝未在 allowlist 的 `tool_id`。  
3. 观测：`experience_sink` 打 `tool_backend=http_sim_bridge`（若启用）。

---

## 与模块一、二的协同小结

- **模块一**：AdamI **消费** 外部 MCP Server（Docker stdio）；路径 A 是 AdamI **提供** Server 给 Sim **消费**——方向相反，但 **allow/deny、契约 ID** 应对齐同一套配置源。  
- **模块二**：mcp-agent 作为 **Client** 聚合 MCP；Sim 也可作为 Client；**不要**假设三者共享同一连接池，以 **tool_id + 契约** 为一致语言。

---

## 集成测试（端到端）

- 自动化：**默认跳过**；见 `tests/integration/test_sim_mcp_bridge_e2e.py`，标记 `pytest.mark.integration`。  
- 手工：Sim 画布添加 MCP 工具 → 指向 AdamI Server（路径 A）或 curl HTTP（路径 B）→ 单次 `tools/call` 成功且内核日志无未授权告警。

**环境变量（可选启用 E2E）**

- `ADAMI_SIM_MCP_E2E=1`：在具备 MCP Server 镜像与 Sim 实例的环境中运行集成用例（当前仓库内仍为占位跳过，避免默认 CI 依赖 Docker）。

---

## 技术桩（代码）

- `src/adami_kernel/integration/sim/mcp_bridge.py`：`SimMcpBridgePath` 枚举与文档路径常量，供后续 Server 启动器与测试引用。
