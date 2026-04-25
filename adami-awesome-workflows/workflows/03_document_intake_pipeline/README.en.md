## 03_document_intake_pipeline (Document Intake Pipeline)

> 中文版：`README.md`

Goal: demonstrate AdamI’s “documents → structured knowledge” value in enterprise scenarios: convert
to Markdown, archive into Inbox/SecondBrain, and reuse later for retrieval and reporting.

### Prerequisites

- For stronger document parsing, enable MarkItDown:

```bash
poetry install -E markitdown
```

### Demo script (CLI)

1. Start AdamI CLI:

```bash
poetry run adami
```

2. Place a `pdf/docx/pptx/xlsx` file on disk (example: `/tmp/demo.docx`).
3. Trigger intake in the CLI (the exact command depends on which intake/document routes are enabled;
   run `help` first to discover available commands).

### Value points (talk track)

- **Unified pipeline**: many formats in, consistent Markdown out.
- **Private & compliant**: parsing and storage can run in your private environment; combine with sensitive redaction and OTel export redaction.
- **Reusable**: downstream workflows can reference archived Markdown/Inbox content for review, Q&A, and reports.

