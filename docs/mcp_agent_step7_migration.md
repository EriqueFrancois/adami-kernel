# 步骤 7 — MCP 双栈渐进替换与收敛（可选 · 后期）

在 **契约层稳定**（步骤 2）、**试点与回归稳定**（步骤 3–6）之后，再评估是否 **删除或收敛** 部分自研 MCP 路径，把 **会话管理** 为主交给 mcp-agent，**宿主机隔离** 仍由 Docker 策略保证。本文档为 **策略 + 开关说明 + 单写迁移清单**；**不在此阶段改代码删路径**。

---

## 1. 目标与边界

| 目标 | 说明 |
|------|------|
| 降低长期维护成本 | 避免无限期维护两套「发现工具 + 调 tools/call + 会话」实现 |
| 不牺牲安全默认 | **§3.1** 挂载白名单、只读 rootfs、`no-new-privileges` 等仍适用；Docker **argv 构建** 已与 `mcp_agent_config.docker_run_args_for_mcp_spec` 对齐，可长期复用 |
| 可回滚 | 任意阶段保留「关开关即回第一模块」能力，直至单写验收签字 |

**边界**：全局编排仍以 `WorkflowEngine` / `MultiAgentOrchestrator` / `TaskPlanner` 为准；mcp-agent **不**取代内核主循环（见 `mcp_agent_alignment.md` §1）。

---

## 2. 当前双栈对照（写清再动刀）

| 能力 | 第一模块（自研） | mcp-agent 路径 |
|------|------------------|----------------|
| 配置源 | `ADAMI_MCP_SERVERS_JSON` | 同左 → `build_mcpserver_settings_map` |
| Docker 隔离 | `McpDockerStdioRunner` + `docker_run_args_for_mcp_spec` | 同构 `MCPServerSettings(command="docker", args=…)` |
| 工具发现 / 注册 | `McpManager` → `register_tool` + `dynamic_skills` | 不替代注册表；执行可走 `try_execute_via_mcp_agent` |
| 单次 tools/call | `call_mcp_tool(runner, spec, …)` | `Agent.call_tool`（经 `tool_executor`） |
| 试点开关 | `ADAMI_MCP_ENABLED` | `ADAMI_USE_MCP_AGENT` / `ADAMI_USE_MCP_AGENT_PLANNER` |
| 审计 | `experience_sink` `tool_call`（步骤 5） | 同左；`tool_backend`=`mcp_agent` / `mcp_docker` |

---

## 3. 双写期：Feature flag（已有 + 建议）

### 3.1 已存在（生产可组合）

| 变量 | 作用 |
|------|------|
| `ADAMI_MCP_ENABLED` | 第一模块是否加载 MCP、注册工具 |
| `ADAMI_MCP_MODULE_AGENT_ENABLED` | 第二模块总闸；`false` 时忽略下方两开关（不关第一模块） |
| `ADAMI_USE_MCP_AGENT` | Planner/分发路径上 MCP 工具是否 **优先** 经 mcp-agent 执行；失败回退 Docker |
| `ADAMI_USE_MCP_AGENT_PLANNER` | 是否在规划链上尝试 `planner_bridge`（Orchestrator 试点） |

**双写语义**：`ADAMI_MCP_ENABLED=true` 且 `ADAMI_USE_MCP_AGENT=true` 时，同一 `tool_id` 可先经 mcp-agent，失败仍走已注册的 `dynamic_skills`（Docker）。

### 3.2 建议新增（单写切换前在配置中落地）

以下 **尚未在代码中实现**，作为单写期显式闸；实现时应用一处枚举，避免散落魔法字符串：

| 建议变量 | 取值示例 | 含义 |
|----------|-----------|------|
| `ADAMI_MCP_EXECUTION_MODE` | `dual_write`（默认） / `mcp_agent_primary` / `legacy_only` | 是否允许双写、是否禁止 mcp-agent、是否禁止回退 Docker |
| `ADAMI_MCP_SHADOW_COMPARE` | `false` / `true` | 影子模式：两路都跑，只比对结果不落业务差异（运维/压测） |

实现前：**仅用现有三开关** 完成影子对比即可（日志 + 经验池 + 人工抽检）。

---

## 4. 关键检测：同一份配置下「列表 + 调用」一致

在 **同一** `ADAMI_MCP_SERVERS_JSON`、同一 allow/deny、同一环境：

1. **工具列表（契约层）**  
   - 导出 `tool_contract_registry` 中 `source=mcp` 的 `tool_id` 集合（排序后）。  
   - 双写期：`ADAMI_USE_MCP_AGENT=0` 与 `=1`（成功走 pilot）下，Planner/LLM 可见工具块应一致（`to_llm_prompt_fragment` 或等价列表）。

2. **调用结果**  
   - 固定 `tool_id` + 固定 `args`（JSON），分别走：  
     - 仅 Docker：`ADAMI_USE_MCP_AGENT=false`；  
     - mcp-agent 成功路径：`ADAMI_USE_MCP_AGENT=true` 且 pilot 不降级。  
   - 比较 **业务语义**：结构化结果 JSON 归一化后应等价；纯文本允许首尾空白归一。  
   - **错误类**：双方应对同一类失败给出可预期的错误边界（超时、容器退出）；不要求字符串逐字相同。

3. **审计**  
   - `experience_sink` 中对应 `trace_id` 能还原 `tool_id`、`tool_backend`、`latency_ms`、`args_summary` / `result_summary`（步骤 5）。

**自动化建议**：在具备 Docker 与测试 MCP 镜像的 CI job 中，增加「双路径对比」用例（可标记 `@pytest.mark.integration` / `@pytest.mark.docker`），默认 job 跳过。

---

## 5. 单写期迁移 Checklist（签字前逐项打勾）

**阶段 A — 影子与数据**

- [ ] 生产或预发 **双写** 运行 ≥ 约定天数（如 14d），无未解释 P1。
- [ ] 抽样对比：工具列表 diff 为空；核心 N 个 tools/call 结果一致（见 §4）。
- [ ] `experience_sink` / 日志中 `mcp_agent` 与 `mcp_docker` 比例与预期一致，无异常飙升。

**阶段 B — 开关收敛**

- [ ] 默认生产：`ADAMI_USE_MCP_AGENT=true`（或等价单写主路径），且 **回退路径** 仍可在 incident 时一键关闭。
- [ ] 文档与 Runbook 更新：on-call 知道如何切回 `legacy_only`（若已实现 `ADAMI_MCP_EXECUTION_MODE`）。

**阶段 C — 代码删除/收敛（最后做）**

- [ ] 删除或降级 **仅** 在单写验证后确认无调用的路径（例如：若 100% 走 mcp-agent，可考虑将 `call_mcp_tool` 从热路径移除，仅保留测试夹具）。
- [ ] **保留**：`mcp_agent_config.docker_run_args_for_mcp_spec`、`spec` 解析、allow/deny、**McpManager 注册**（直至 LLM 工具发现完全改由单一来源）。
- [ ] 更新 `docs/mcp_agent_alignment.md` 概念表：标明「会话默认 mcp-agent / 执行默认 xxx」。

**回滚**

- [ ] 保留 `ADAMI_MCP_ENABLED` + `ADAMI_USE_MCP_AGENT=false` 可在单版本内恢复 Docker 主执行，无需回滚发布（若架构仍支持）。

---

## 6. 不建议过早删除的模块

| 路径 | 原因 |
|------|------|
| `src/adami_kernel/mcp/docker_stdio_runner.py` | Docker 传输与超时仍可能被 mcp-agent 或应急路径使用 |
| `src/adami_kernel/mcp/tool_adapter.py` | allow/deny 与 `map_tool_name` 与注册表一致 |
| `src/adami_kernel/integration/mcp_agent/mcp_agent_config.py` | **双栈共享** Docker argv；删则 mcp-agent 侧需重复安全策略 |
| `McpManager` | 在「工具只从 mcp-agent 发现」未验证前，勿删注册入口 |

---

## 7. 相关文档与代码

- 对齐总览：`docs/mcp_agent_alignment.md`
- 契约：`src/adami_kernel/integration/mcp_agent/contracts.py`
- 工具执行试点：`src/adami_kernel/integration/mcp_agent/tool_executor.py`、`EvolutionEngine.execute_tool_dispatch`
- 回归：`tests/test_mcp_agent_adapter_smoke.py`、`tests/test_acceptance_mcp_agent_step6_smoke_matrix.py`

---

**结论**：步骤 7 **以文档与清单为主**；**实际删代码** 仅在完成 §4 检测与 §5 Checklist 后执行，并保留 Docker 隔离与配置映射的单一事实来源（`mcp_agent_config` + `ADAMI_MCP_*`）。
