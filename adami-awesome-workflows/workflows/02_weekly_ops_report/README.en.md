## 02_weekly_ops_report (Weekly Ops Report)

> 中文版：`README.md`

Goal: demonstrate AdamI’s “operator-ready deliverable” capability in private deployments (scheduled,
configurable, auditable reporting).

### Prerequisites

- Kernel is running (CLI / Telegram / Discord any is fine)
- Optional: SecondBrain initialized (default boot flow initializes it)

### Demo script (CLI)

In the AdamI CLI:

- **List configs**:
  - `/report list`
- **Show the weekly config**:
  - `/report show weekly`
- **Set the weekly config** (example JSON; customize for your business):

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

- **Run weekly report now**:
  - `/report run weekly`

### Value points (talk track)

- **Configurable**: replace templates via `/report set` without redeploying code.
- **Auditable**: generation and outputs can be recorded via logs/SecondBrain.
- **Multi-channel delivery**: same output can be delivered to CLI/Web/IM depending on your deployment.

