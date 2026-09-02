## 评测与回放（开发者指南）

AdamI 已有较完整的单元/验收测试体系，但“实用 Agent”的演进需要 **行为级回归测试**：golden traces + replay + scoring。

本指南描述 vNext（Milestone B）的现状与使用方式：**golden traces + 确定性回放 + 评分 + CI 门禁**。

### 当前已有（vNext / Milestone B）

- **Golden trace 套件包**：`docs/evals/traces/`（见 `docs/evals/traces/README.md`）
- **回放 runner**（导出回放后的 trace，并支持强门禁）：
  - `poetry run adami-replay-run <trace.ndjson> --out-trace <replayed.ndjson>`
  - `--verify-isomorphic`：严格“同构”对齐校验（带归一化）
  - `--inject-all-records`：注入所有 trace record（比只注入 prompt 更强）
  - `--full-kernel`：prompt 驱动（注入 `user.prompt`，让内核自然跑）
  - `--faults <faults.json>`：Phase 3 故障注入；可输出 eval 报告
- **回放评测**（suite 级 JSON + Markdown 报告）：
  - `poetry run adami-replay-eval --suite-dir docs/evals/traces --out-json out.json --out-md out.md`
- **对比报告**（baseline vs head 差异 + 阈值）：
  - `poetry run adami-replay-compare --baseline-json base.json --head-json head.json --out-json cmp.json --out-md cmp.md`
  - 阈值：`--max-score-drop`、`--max-dim-drop`
  - ref 模式（跨代兼容）：`--baseline-ref <ref> --head-ref <ref> --suite-dir ... --out-dir ...`

### CI 门禁（摘要）

CI 已接入 (a) suite eval 门禁、(b) 强同构门禁、(c) inject-all 门禁，并用 allowlist 管控覆盖面。

- allowlist 配置文件：
  - `docs/evals/traces/isomorphic_gate.json`
  - `docs/evals/traces/inject_all_gate.json`
- CI 也包含 “故障注入 smoke（预期失败）”，用于证明链路端到端可用。

### 评分卡（我们实际门禁的维度）

每条 trace 都有 `scorecard.json`，显式配置门槛。核心维度包括：

- **Correctness**：任务是否完成、关键字段是否齐全
- **Safety**：禁词/泄露硬规则 + 脱敏
- **UX**：用户可见回复是否清晰、可操作
- **Noise**：避免无意义 filler/刷屏
- **Operability**：工具生命周期事件完整、超时/错误后有可操作回复
- **Latency/Cost**：尽力而为的性能代理，用于稳定回归对比

