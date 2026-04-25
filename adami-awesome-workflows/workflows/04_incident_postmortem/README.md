## 04_incident_postmortem（故障复盘工作流）

> English: `README.en.md`

目标：在企业场景中快速展示 AdamI 对“事件复盘”的价值：从零散信息生成可交付的 RCA 草案与行动项列表。

### 输入（示例）

你可以把以下信息作为一次任务输入（CLI/IM 都可）：

- 事件时间范围
- 影响范围（用户数、服务、区域）
- 关键日志/告警摘要
- 临时处置动作

### 演示脚本（CLI）

在 CLI 中粘贴一段任务描述，例如：

> 请根据下面信息生成一次 Postmortem 草案：包含 Timeline、Root Cause、Contributing Factors、Customer Impact、Detection、Mitigation、Action Items（含 owner 与 due date 建议）。信息如下：...

### 输出（期望）

- Timeline（按时间线排序）
- RCA（主因 + 诱因）
- 行动项（可落地、可追踪）

### 商业价值展示点

- **减少复盘人力成本**：把“整理资料/结构化输出”交给 Agent 协作引擎完成。
- **可审计**：输入与输出可结合 SecondBrain/工作流状态留痕。
- **可集成**：下一步可对接工单系统/知识库/告警平台（Enterprise 版常见需求）。

