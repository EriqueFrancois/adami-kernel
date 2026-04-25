# AdamI — Security & trust boundaries

**Audience**: security auditors, compliance reviewers, buyer diligence teams.

This document maps **implemented controls** in the open tree. It is **not** a penetration-test report.

---

## 1. Threat model (scope)

In scope:

- **Secrets in motion**: user text, tool payloads, logs.
- **Untrusted code paths**: downloaded or LLM-generated “skills”.
- **Execution isolation**: optional Docker-backed sandboxes.

Out of scope for this repo:

- Your cloud IAM, VPC boundaries, KMS policies — must be layered **outside** the kernel.

---

## 2. Event-bus middleware — sensitive redaction

**Component**: `adami_kernel.guardian.sensitive_filter.SensitiveFilter`

- Registered in `EventBus.initialize()` as middleware.
- Regex families cover API-key-like material, passwords, phones, emails, card patterns, and generic `secret|token|auth|key` assignments.
- **Recursive** redaction over `event.payload` dict/list structures with cycle protection.
- Certain keys (`chat_id`, `discord_channel_id`, …) are allow-listed to avoid breaking routing while scrubbing secrets.

**Limitation**: regex defense-in-depth is not perfect — pair with **least-privilege keys** and external DLP for regulated data.

---

## 3. AST auditing — plugin & foreign code

**Component**: `adami_kernel.orchestrator.loader.PluginLoader.audit_code`

- Parses Python to AST and walks nodes.
- Blocks forbidden imports (`os`, `sys`, `subprocess`, …), dangerous builtins (`eval`, `exec`, `open`, …), risky attribute/call shapes, and string literals matching known hostile patterns.
- Returns **`bool`**: `False` rejects load.

**Downstream**: `SkillInspector` / `ClawHub.download_and_audit` call this gate before accepting external DNA.

---

## 4. Skill washing — AST transform on generated skills

**Component**: `adami_kernel.skill_manager.skill_washer.SkillWasher`

- Uses `ast.NodeTransformer` to replace calls matching a **danger keyword list** (e.g. `os.system`, `subprocess`, `eval(`) with a raising stub.
- Falls back to string-level stripping if AST parsing fails, then may return a **minimal safe template**.

This is a **second line** after auditing — oriented toward LLM-produced code.

---

## 5. Secret vault (local signing material)

**Component**: `adami_kernel.guardian.tls.LocalSecretVault`

- Persists a JSON keystore (`settings.path_keystore_json`) with a generated `master_node` key (`secrets.token_hex(32)`).
- On POSIX attempts `chmod 0o600` on the keystore file.
- Exposes `generate_token` / `verify_token` using **HMAC-SHA256** for payload attestation.

**Operational guidance**: treat the keystore like a machine secret; back up only via secure channels.

---

## 6. Dream sandbox (optional code execution)

**Component**: `adami_kernel.cortex.dream_sandbox.DreamSandbox`

- Uses Docker when available; documented intent includes **bridge networking** and **dummy API keys** in the container environment to reduce accidental exfiltration to real providers from sandboxed runs.
- If Docker is unavailable, behavior degrades with explicit logging — do not assume isolation.

---

## 7. RBAC & DLQ hooks

`EventBus` supports optional `rbac` and `dlq_db`:

- Failed publishes / blocked middleware may enqueue to DLQ for later replay (see `bus.py`).

---

## 8. Cooperative restart

`LifecycleManager.request_process_restart()` flags a post-shutdown `execv` restart. **Threat consideration**: anyone who can trigger that command in your deployment can cause **availability impact** — protect Telegram/Discord tokens and admin surfaces.

---

## 9. Hardening checklist (deployment)

1. Rotate LLM & messenger tokens regularly; keep them only in `.env`.
2. Run kernel under a dedicated service account with **no** host Docker socket if not required.
3. Enable centralized logging with retention policies; scrub attachments policy-side.
4. Run `poetry run ruff check` + `pyright` + pytest in CI (see `CONTRIBUTING.md`).
