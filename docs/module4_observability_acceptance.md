# 模块四观测与验收（步骤 7）

目标：Sim 可回放轨迹与经验池中与 **阶段边界** 对齐的字段（`phase`、`checkpoint_seq`），便于量化「阶段数、checkpoint 写成功次数、恢复是否命中 last_good」。

## 1. 字段契约

| 位置 | 字段 | 说明 |
|------|------|------|
| `workflow.events` → `AdamiEvent.payload`（`PHASE_TRANSITION`） | `phase` | 与 `to_phase` 一致，便于消费者只读顶层 |
| 同上 | `checkpoint_seq` | 当次 `save_workflow_phase_checkpoint` 成功后的序号；未写库则为 `null` |
| Sim `ReplayTraceRecordV1` | `phase`, `checkpoint_seq` | `integration/sim/trace_sink.py` 的 `event_to_record` 从脱敏 payload 提取 |
| `WorkflowState.history`（`phase_transition`） | `checkpoint_seq` | 可选，与库内该阶段最新信封一致 |
| 经验池 `ExperienceRecord` | `phase`, `checkpoint_seq` | `type=phase_transition`，与 Sim 语义对齐 |

## 2. 自动化回归

```bash
poetry run pytest tests/test_long_task_phases.py tests/test_long_task_phase_gate.py tests/test_sim_trace_export.py -q
```

## 3. NDJSON 快速统计

在开启 `ADAMI_SIM_TRACE_EXPORT_ENABLED` 并产生 `eventbus.ndjson` 后：

```bash
python scripts/module4_trace_summary.py .adami_data/traces/eventbus.ndjson
```

输出含 `phase_transition_events`、`checkpoint_seqs` 等，可用于演示或门禁阈值（例如阶段迁移次数 ≥ 预期）。

## 4. 手动验收：杀进程后重启续跑（提纲）

以下为用户态/运维演示步骤，**不替代**自动化测试；按实际部署入口（CLI / Discord / API）替换启动命令。

1. **准备**：在 `config.py` 或环境变量中开启 `ADAMI_LONG_TASK_TRACKING_ENABLED`（或对工作流设 `metadata.long_task_tracking_enabled=True`）。可选开启 `ADAMI_SIM_MODULE_ENABLED` + `ADAMI_SIM_TRACE_EXPORT_ENABLED`，指定 `ADAMI_SIM_TRACE_EXPORT_PATH`。
2. **启动**内核或仅跑一条会触发 `WorkflowEngine` + 阶段闸的长任务工作流（含多节点路由或 Multi-Agent 角色切换）。
3. **确认**：在轨迹文件或日志中看到 `PHASE_TRANSITION`，且 NDJSON 记录含 `phase` / `checkpoint_seq`（可用上一节脚本统计）。
4. **杀进程**：`SIGKILL` / `kill -9` 模拟硬崩溃（勿优雅 shutdown）。
5. **重启**后仅依赖持久化：`LayeredMemory` 中同一 `workflow_id` 的 `workflow_state` 与 `last_good` checkpoint 应仍在；通过既有 **resume** / **HITL 恢复** 入口继续（具体命令取决于产品封装）。
6. **验收**：恢复后 `context.current_phase` 与 `get_last_good_checkpoint` 一致；新产生的轨迹中阶段序列可接续；若使用步骤 4 的回滚路径，应看到 `phase_recovery_payload` 等已有字段。

若你的部署尚未暴露「仅 workflow_id 恢复」的 CLI，可在集成测试层用 `tests/test_long_task_failure_recovery.py` 与 `tests/test_long_task_phases.py` 代替本节的运行时操作。

## 5. 量化建议（模块四完成度）

- **阶段迁移次数**：NDJSON 中 `event_type==PHASE_TRANSITION` 条数，或 `scripts/module4_trace_summary.py` 的 `phase_transition_events`。
- **带序号的 checkpoint 事件**：`with_top_level_checkpoint_seq`（侧车/未写库阶段可能为 0）。
- **恢复成功率**：在注入 `phase_fatal` 的测试中已有断言；生产可统计 `workflow_node_failure` 审计里 `recovery_action` 为回滚且后续 `SUCCESS` 的比例。
