## 03_document_intake_pipeline（文档摄取管线）

> English: `README.en.md`

目标：展示 AdamI 在企业常见“文档 → 结构化知识”场景中的落地价值：自动转 Markdown、入 Inbox/SecondBrain、后续可检索与复用。

### 依赖

- 如需更强的文档解析能力，建议启用 MarkItDown：

```bash
poetry install -E markitdown
```

### 演示脚本（CLI）

1. 启动 AdamI CLI：

```bash
poetry run adami
```

2. 将一份 `pdf/docx/pptx/xlsx` 放到本机路径（示例：`/tmp/demo.docx`）。
3. 在 CLI 中触发摄取（具体命令取决于你当前启用的 intake/文档管线路由；建议先用 `help` 查看已启用指令）。

### 商业价值展示点（建议话术）

- **统一管线**：同一条路径处理多格式输入，输出统一 Markdown。
- **可控与合规**：可以在私有化环境里完成解析与存储；结合敏感信息过滤与 OTel 脱敏策略。
- **可复用**：后续工作流可直接引用摄取后的 Markdown/Inbox 内容做总结、审核、问答与报表。

