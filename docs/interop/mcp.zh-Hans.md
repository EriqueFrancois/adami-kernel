## MCP 互操作边界（vNext）

### 为什么是 MCP

在 2026 年，MCP 正在成为事实上的工具连接标准（agent → tools）。AdamI 已有 MCP 的内部实现基础，但 vNext
把它提升为 **产品化边界**：文档清晰、可观测、默认安全。

#### 2026 趋势要点（为什么这对商业与落地重要）

- MCP 越来越像“工具 USB-C”：买方期待标准化的工具接口与生态兼容。
- 生产落地重点在边界层：**allowlist 策略**、**身份/OAuth**、**可观测与审计**。

### 目前已有（v1.0-alpha）

- `src/adami_kernel/mcp/manager.py`：加载 server spec 并把 tools 注册到：
  - EvolutionEngine 的 tool schema + dynamic executor
  - ToolboxManager 外部工具注册表（若存在）
- 热更新：后台 fingerprint 轮询 settings 变化后重建工具列表

### vNext 需要补齐

#### 1) 默认安全与策略

- 默认拒绝（deny-by-default），仅 allowlist 明确允许的工具（`ADAMI_MCP_ALLOW_TOOLS`）。
- 明确超时策略（`ADAMI_MCP_TIMEOUT_SEC`）与错误分类。
- 清晰说明 MCP server 的 secrets/env 传递与隔离边界（避免“隐式信任”）。

#### 2) 可观测映射

每次 MCP 工具调用应产出：

- trace span：`tool.mcp.call`，带属性：
  - `tool.name`、`mcp.server`、`mcp.tool_name`
  - `status`（`ok|timeout|error`）
- 审计元数据：脱敏后的输入、响应大小、耗时等

#### 3) 工具发现与运维 UX

- 提供“当前可用 MCP 工具清单”命令
- 在日志中展示 allow/deny 决策（但不泄露参数）

### 非目标

- 在没有组织策略层的情况下把 MCP 暴露到公网
- 默认信任任意第三方 server（默认应视为不可信）

