## AdamI Private Deployment Guide (Local LLM Integration)

> 中文版：`private_local_llm_deployment_guide.md`

This guide targets **private / offline deployments** and documents AdamI’s currently integrated
local model stack:

- **Ollama (Linux / macOS)**: the final local LLM fallback.
- **MLX (macOS-first)**: preferred on Apple Silicon; automatically degrades to Ollama on failure.

Implementation pointers (for audits and customization):

- Hybrid router: `src/adami_kernel/cortex/router.py` (local-first + cloud failure → local fallback)
- Local LLM settings: `src/adami_kernel/config.py` (`OLLAMA_*` / `ADAMI_MLX_*`)
- Ollama auto-start: `src/adami_kernel/core/boot_manager.py` (optional)

---

## 1. Target topology (recommended)

Minimal single-node setup:

- AdamI Kernel (enable CLI/Web/Telegram/Discord as needed)
- Ollama (local inference service)
- Optional: OTel Collector (forward traces/metrics into your internal observability stack)

---

## 2. Minimal configuration (local-only)

In `.env` (or your secret manager), set:

- **Enable Ollama** (enabled by default):
  - `OLLAMA_ENABLED=true`
  - `OLLAMA_HOST=http://127.0.0.1:11434`
  - `OLLAMA_MODEL=qwen3.5:9b` (example; replace with a pulled model)
- **Disable cloud LLMs** (optional but recommended for private deployments):
  - do not set any `*_API_KEY`, and/or
  - leave provider `api_key` empty (the router filters empty keys)

Notes:

- Even if cloud providers are configured, `HybridLLMRouter` degrades to local MLX/Ollama on network
  errors/timeouts/429s, so workflows don’t exit just because the cloud is flaky.

---

## 3. Deploying Ollama (Linux systemd recommended)

### 3.1 Install and start

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
```

Health check:

```bash
curl -s http://127.0.0.1:11434/api/version
```

### 3.2 Pull a model

```bash
ollama pull qwen3.5:9b
```

### 3.3 Networking guidance

Prefer `127.0.0.1` when co-located, so you don’t expose inference endpoints on your LAN.

If you must run Ollama remotely:

- bind only to internal interfaces
- enforce ACL/firewall rules
- consider reverse proxy + mTLS

---

## 4. Deploying MLX (macOS / Apple Silicon)

AdamI loads MLX inside the router:

- `ADAMI_MLX_ENABLED=true`
- `ADAMI_MLX_MODEL_PATH=mlx-community/Qwen3.5-9B-MLX-4bit` (default)

Operational notes:

- MLX is enabled only on macOS (`Darwin`). Import/load failures automatically disable MLX and fall
  back to Ollama.
- Under high load, `unload_mlx_model()` can proactively free memory (the router will attempt this
  when MLX calls fail).

---

## 5. Running AdamI (Poetry)

```bash
poetry install
poetry run adami
```

For production/private deployments:

- run under a dedicated least-privilege account
- set `ADAMI_RUNTIME_PROFILE=production`
- enable OTLP export when you have a collector (next section)

---

## 6. Observability (recommended)

By default, AdamI exports spans to console (no collector required):

- `ADAMI_ENABLE_OBSERVABILITY=true`
- `ADAMI_OTEL_EXPORTER=console`

To export OTLP gRPC:

- `ADAMI_OTEL_EXPORTER=otlp`
- configure your OTLP endpoint (see `src/adami_kernel/web/otel.py` and `.env.example`)

Data safety:

- sampling and export-time redaction are implemented in `src/adami_kernel/observability/otel_export_policy.py`
- for private deployments, keep redaction enabled: `ADAMI_OTEL_EXPORT_REDACT_ENABLED=true`

---

## 7. Troubleshooting

### 7.1 Ollama isn’t running

AdamI may attempt auto-start during boot:

- Linux: `systemctl start ollama`
- macOS: `ollama serve`

If you don’t want AdamI to manage Ollama lifecycle, ensure Ollama is started before AdamI, or
disable auto-start in your deployment policy.

### 7.2 Slow responses or timeouts

Tune:

- `ADAMI_ROUTER_OLLAMA_TIMEOUT_SEC` (default 120s)
- model size vs hardware (CPU/RAM/disk)
- Ollama options in `router.py` payload (`num_ctx` / `num_predict`)

### 7.3 MLX load failures (macOS)

Common causes:

- model path not available / first-time download
- insufficient RAM

Validate the Ollama-only path first, then enable MLX.

