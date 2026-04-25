## adami-awesome-workflows

`adami-awesome-workflows` is a collection of example workflows and configuration templates for
AdamI. The goal is to quickly demonstrate **commercial value** in private/enterprise scenarios.

> 中文版：`README.zh-Hans.md`

### Structure

- `templates/`
  - `.env.private.example`: private deployment env template (local LLM / OTel / safer defaults)
  - `docker-compose.ollama.yml`: single-node Ollama compose (local inference foundation)
  - `otel-collector.config.yml`: optional OTel Collector config example
- `workflows/`
  - `02_weekly_ops_report/`: weekly ops report (Report Studio + SecondBrain)
  - `03_document_intake_pipeline/`: document intake → Markdown → Inbox/SecondBrain
  - `04_incident_postmortem/`: incident postmortem (timeline + RCA draft + action items)

### Quick use (demo)

1. Copy templates and fill your environment variables (local inference first)
2. Start AdamI (CLI or Web)
3. Follow `workflows/*/README.md` demo scripts to produce deliverables

> Note: this folder is for “examples and templates”. Enterprise delivery typically stores workflows
> and configs in a dedicated repo/artifact store with governance and audit controls.

