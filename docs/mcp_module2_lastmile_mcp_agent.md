# 第二模块 — lastmile-ai / mcp-agent（基于 MCP 的 Agent 框架）

短文档：说明 AdamI **第二模块**（可选 extra **`mcp-agent`**）的职责边界、与第一模块的配合方式及配置入口。

## 0. 范围冻结与依赖

| 项 | 约定 |
|----|------|
| **包** | PyPI `mcp-agent`（仓库 pin 见 `pyproject.toml`；安装：`poetry install -E mcp-agent`） |
| **上游** | [lastmile-ai/mcp-agent](https://github.com/lastmile-ai/mcp-agent) — Agent、Orchestrator、`MCPApp`、会话与工具聚合 |
| **默认** | `poetry install` **可不**安装该发行包；未安装时第二模块代码路径应 **可导入失败或短路**，不影响内核主循环 |
| **依赖冲突** | 与 `numpy` / `rich` 等版本关系见 `docs/mcp_agent_alignment.md` §0 |

## 1. 概念映射（防双编排）

| mcp-agent 概念 | AdamI 侧 | 谁负责 |
|----------------|----------|--------|
| `MCPApp` + `MCPServerSettings` | `ADAMI_MCP_SERVERS_JSON` → `mcp_agent_config.build_mcpserver_settings_map` | 集成层 |
| `Agent.call_tool` | `tool_executor.try_execute_via_mcp_agent`（Planner/Evolution 分发） | 第二模块执行试点 |
| `create_orchestrator` / 规划试点 | `planner_bridge`（`ADAMI_USE_MCP_AGENT_PLANNER`） | 可选分支；失败回退原规划链 |
| LLM Provider | `ADAMI_MCP_AGENT_LLM_PROVIDER` + 各 `*_API_KEY` | 适配层选路；主对话仍以 `HybridLLMRouter` 为准 |

**一句话**：第二模块是 **可选工具运行时 + 可选规划片段**；全局编排仍以 `WorkflowEngine` / `MultiAgentOrchestrator` / `TaskPlanner` 为主。

## 2. 配置一览（与 `config.py` 对齐）

| 变量 | 含义 |
|------|------|
| `ADAMI_MCP_MODULE_AGENT_ENABLED` | **模块二总闸**：`false` 时忽略下方 `ADAMI_USE_MCP_AGENT*`，一键关闭 mcp-agent 路径（**不**关闭第一模块 `ADAMI_MCP_ENABLED`） |
| `ADAMI_USE_MCP_AGENT` | 工具执行是否 **优先** 经 mcp-agent；失败回退第一模块 Docker |
| `ADAMI_USE_MCP_AGENT_PLANNER` | 是否在规划链上尝试 `planner_bridge` |
| `ADAMI_MCP_AGENT_LLM_PROVIDER` | `openai` / `anthropic` / `google` 等；空则按已有密钥启发式 |
| `ADAMI_MCP_AGENT_PLAN_TYPE` | 传入 `create_orchestrator` 的 `plan_type`（默认 `iterative`） |

Server 列表、Docker 安全参数与第一模块 **同源**：`ADAMI_MCP_SERVERS_JSON`、`ADAMI_MCP_MOUNT_ALLOWLIST`、`ADAMI_MCP_READ_ONLY_FS` 等。

### 有效开关（代码 helpers）

- `mcp_agent_tool_execution_effective(settings)` ≡ 总闸 ∧ `ADAMI_USE_MCP_AGENT`
- `mcp_agent_planner_pilot_effective(settings)` ≡ 总闸 ∧ `ADAMI_USE_MCP_AGENT_PLANNER`

定义见 `src/adami_kernel/config.py`。

## 相关路径

- Sim 画布 MCP 互操作（模块三）：`docs/sim_mcp_bridge.md`
- 对齐与版本：`docs/mcp_agent_alignment.md`
- 适配器：`src/adami_kernel/integration/mcp_agent/adapter.py`
- 共享 Docker 映射：`src/adami_kernel/integration/mcp_agent/mcp_agent_config.py`
- 工具执行：`src/adami_kernel/integration/mcp_agent/tool_executor.py`
- 规划桥：`src/adami_kernel/integration/mcp_agent/planner_bridge.py`
- 渐进替换（后期）：`docs/mcp_agent_step7_migration.md`
