# mcp-agent × AdamI 对齐说明（步骤 0–1）

短文档：边界与安装策略，避免双编排与隐式假设。

**模块说明（扩展阅读）**

- 第一模块（原生 Docker stdio MCP）与 **mcp-use** 生态：`docs/mcp_module1_mcp_use.md`
- 第二模块（**lastmile-ai mcp-agent**）配置与开关：`docs/mcp_module2_lastmile_mcp_agent.md`

## 0. 范围冻结与依赖（extras）

| 项 | 约定 |
|----|------|
| **Extra 名称** | `mcp-agent`（与 `adami-kernel[mcp-agent]`、`poetry install -E mcp-agent` 一致） |
| **包 pin** | `mcp-agent==0.2.6`（Poetry：`optional` 主依赖中固定版本） |
| **默认安装** | `poetry install` **不安装** `mcp-agent` 包；仅安装 lock 中解析出的**传递**依赖（见下） |

### 冲突与对齐结论（必读）

PyPI `mcp-agent` 声明 **`rich>=13.9.4`**、**`numpy>=2.1.3`**。AdamI 历史基线为 **`numpy<2`**、`rich==13.7.1`（litellm 等）时，**无法**在 **单一 Poetry lockfile** 内同时满足「主基线」与「声明 optional `mcp-agent`」——`poetry lock` 会直接失败。

**当前仓库选择（与方案对齐方式）**：为通过「`poetry install -E mcp-agent` 可成功」类检测，主依赖中 **放宽** `rich`、`numpy` 至与 `mcp-agent` 兼容；**代价**是默认 `poetry install` 也会解析到 **numpy 2.x / rich≥13.9.4**（Poetry 单锁语义，**不是**「只装 extra 才升级 numpy」）。

若必须长期保持 **numpy&lt;2** 且不在主锁引入 `mcp-agent`：**不要**在 `pyproject.toml` 中声明该 optional 依赖；在**独立 venv** 内 `pip install mcp-agent==0.2.6` 做 API 验证（该路径**不**受本仓库 lock 约束，需自行处理与 chromadb/mlx 等的兼容性）。

### 关键检测

- `poetry install`（无 extra）：内核可启动；**不**安装 `mcp-agent` 发行包。
- `poetry install -E mcp-agent`：成功安装 `mcp-agent`。
- `pip install -e ".[mcp-agent]"`：在 PEP 517 后端为 `poetry-core` 时，extras 来自 `[tool.poetry.extras]`；需从含 `pyproject.toml` 的仓库根执行（与 Poetry 同套元数据）。

## 1. 概念映射与职责（防双编排）

| mcp-agent 概念 | AdamI 侧对应 | 谁负责 |
|----------------|--------------|--------|
| **MCPApp** + `Settings`（`mcp.servers` 等） | 配置：`ADAMI_MCP_SERVERS_JSON` → 适配层映射为 `MCPServerSettings`；或未来独立 yaml | **集成层** 映射配置；内核不强制启动 MCPApp |
| **Agent(`server_names=`)** | 试点：`planner_bridge` 内 `AgentSpec` / Orchestrator worker | **试点代码**；主 Planner 仍以 `TaskPlanner` + toolbox 为主路径 |
| **AugmentedLLM** | 未接 `HybridLLMRouter`；当前试点用 mcp-agent 自带 OpenAI/Google/Anthropic `Settings` | **LLM**：AdamI 主路径 = `HybridLLMRouter`；mcp-agent 路径 = **其 Provider 客户端**（后续可 shim 到 Router） |
| **workflows / Orchestrator** | `create_orchestrator` 仅用于可选试点分支 | **编排**：默认仍 AdamI `WorkflowEngine` / `MultiAgentOrchestrator`；**禁止**把全局入口换成 MCPApp 主循环 |
| **MCP session / 连接池** | 第一模块：`McpDockerStdioRunner`（按请求起停容器）；mcp-agent：`ServerRegistry` + `MCPConnectionManager` | **Session**：两条实现并存时，**审计与工具名**应对齐同一套前缀（见后续契约步骤） |
| **Tool schema 暴露** | AdamI：`get_registered_tools_for_llm()` 文本 + MCP `tool_adapter`；mcp-agent：由 Agent 聚合 MCP tools | **Schema**：短期两套；目标收敛到**契约层**统一 ID（步骤 2） |
| **执行与审计** | 工具执行：`evolution_engine.toolbox` / MCP runner；经验池：`experience_sink`（mcp-agent 路径待补字段） | **执行**：业务代码；**审计**：AdamI 观测；mcp-agent OTEL 仅作补充对齐 |

**一句话**：mcp-agent 在本仓库中是 **可选工具运行时 + 试点编排片段**，不是第二套全局内核；LLM 主权威仍在 AdamI Router，除非显式 shim。

## 相关路径

- 第一模块说明：`docs/mcp_module1_mcp_use.md`
- 第二模块说明：`docs/mcp_module2_lastmile_mcp_agent.md`
- 依赖：`pyproject.toml` → `optional` `mcp-agent`、`[tool.poetry.extras]` → `"mcp-agent"`
- **契约层（步骤 2）**：`src/adami_kernel/integration/mcp_agent/contracts.py`（`ToolCapability` / `ToolInvocation` / `ToolResult` / `ToolContractRegistry` / `to_llm_prompt_fragment`）
- 试点桥接：`src/adami_kernel/integration/mcp_agent/planner_bridge.py`
- 原生 MCP（Docker stdio）：`src/adami_kernel/mcp/`
- **步骤 7（渐进替换 · 可选后期）**：`docs/mcp_agent_step7_migration.md` — 双写期开关、单写迁移 Checklist、与第一模块 **列表/调用一致性** 检测说明（**不在该文档阶段删代码**）。
