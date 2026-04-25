## 02_weekly_ops_report（每周运营简报）

> English: `README.en.md`

目标：在私有化环境中展示 AdamI 的“可落地运营输出”能力（定期生成、可配置、可审计）。

### 依赖

- Kernel 已启动（CLI / Telegram / Discord 任意一种都可以）
- 可选：SecondBrain 已初始化（默认启动流程会初始化）

### 演示脚本（CLI）

在 AdamI CLI 中输入：

- **列出配置**：
  - `/report list`
- **查看当前周报配置**：
  - `/report show weekly`
- **设置周报配置**（示例 JSON，按你的业务改字段）：

```json
{
  "enabled": true,
  "title": "Weekly Ops Report",
  "sections": [
    {"kind": "fixed_block", "title": "KPIs", "body": "Fill with metrics from your internal system."},
    {"kind": "fixed_block", "title": "Risks", "body": "Summarize incidents and mitigations."},
    {"kind": "fixed_block", "title": "Next Actions", "body": "List top action items for next week."}
  ]
}
```

- **立即执行周报生成**：
  - `/report run weekly`

### 商业价值展示点（建议话术）

- **可配置**：通过 `/report set` 直接替换模板，无需改代码上线。
- **可审计**：生成过程与输出可结合 SecondBrain/日志留痕。
- **多通道分发**：同一输出可推送到 CLI/Web/IM（取决于你的部署接入）。

