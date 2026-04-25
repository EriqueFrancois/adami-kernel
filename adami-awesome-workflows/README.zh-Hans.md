## adami-awesome-workflows

`adami-awesome-workflows` 是 AdamI 的示例工作流与配置模板集合，目标是让你在 **私有化/企业场景** 中快速展示商业价值。

> English: `README.md`

### 内容结构

- `templates/`
  - `.env.private.example`：私有化部署的环境变量模板（本地 LLM / OTel / 安全默认值）
  - `docker-compose.ollama.yml`：Ollama 单机演示编排（可作为 AdamI 私有化推理底座）
  - `otel-collector.config.yml`：可选的 OTel Collector 配置样例
- `workflows/`
  - `02_weekly_ops_report/`：每周运营简报（Report Studio / SecondBrain 结合）
  - `03_document_intake_pipeline/`：文档摄取 → Markdown → Inbox/SecondBrain
  - `04_incident_postmortem/`：故障复盘（时间线整理 + RCA 草案 + 行动项）

### 快速使用（演示）

1. 复制模板并填入你的环境变量（本地推理优先）
2. 启动 AdamI（CLI 或 Web）
3. 按 `workflows/*/README.md` 的“演示脚本”操作，直接输出可展示结果

