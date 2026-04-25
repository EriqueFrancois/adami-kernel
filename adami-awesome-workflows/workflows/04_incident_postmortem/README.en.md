## 04_incident_postmortem (Incident Postmortem Workflow)

> 中文版：`README.md`

Goal: demonstrate AdamI’s value for incident postmortems—turn scattered notes into an actionable,
auditable RCA draft and action-item list.

### Inputs (example)

Provide any of the following as a single task input (CLI/IM are both fine):

- time range
- customer/user impact scope
- key logs/alerts summary
- mitigations already taken

### Demo script (CLI)

Paste a task prompt like:

> Generate a postmortem draft including Timeline, Root Cause, Contributing Factors, Customer Impact,
> Detection, Mitigation, and Action Items (with suggested owner and due date). Info: ...

### Expected output

- Timeline (chronological)
- RCA (primary cause + contributing factors)
- Action items (specific and trackable)

### Value points (talk track)

- **Reduce postmortem labor**: automate structuring, summarization, and action-item drafting.
- **Auditable**: inputs/outputs can be recorded via SecondBrain/workflow state.
- **Integratable**: next step is to connect ticketing/knowledge bases/alerting systems (common Enterprise request).

