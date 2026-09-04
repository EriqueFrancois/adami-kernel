# Guided Demo — future production install (not performed in this change)

This document describes how `adami-demo` would be wired later. **Do not treat this file as an executed deploy.**

## Architecture

```text
Internet
  → existing public edge / tunnel
  → Nginx
  → 127.0.0.1:8091
  → adami-demo (single worker, in-memory sessions)
```

AdamI Demo is a constrained public interaction layer. It exposes only a limited subset of AdamI behavior and does not provide unrestricted access to the full runtime, tools, or production memory.

## Explicit non-goals

- Do not expose Kernel Web Console `:8000`
- Do not expose Health `:8080`
- Do not reverse-proxy `/v1/internal/metrics`
- Do not share production `ADAMI_DATA_DIR`, Second Brain, experience, or task queue
- Do not start Telegram, Discord, DecisionProcessor, Toolbox, or HybridLLMRouter
- This document does not change Nginx, Cloudflare, systemd, or DNS by itself

## Service install (future task)

1. Install the same `adami-kernel` tree the operator already uses (Poetry venv).
2. Copy `deploy/adami-demo.service.example` to systemd **after** review; keep `User=admin` unless the host uses another non-root service account.
3. Bind only `127.0.0.1:8091` and `--workers 1`.
4. Set environment **without committing secrets**:
   - `ADAMI_DEMO_COOKIE_SECRET` and `ADAMI_DEMO_HMAC_SECRET` (required when `COOKIE_SECURE=true`)
   - `ADAMI_DEMO_ALLOWED_ORIGINS` (production site origin)
   - `ADAMI_DEMO_COOKIE_SECURE=true`
   - `ADAMI_DEMO_LLM_PROVIDER=fake` until a provider is approved
   - For live: `ADAMI_DEMO_LLM_PROVIDER=openai_compatible`, `ADAMI_DEMO_LLM_BASE_URL`, `ADAMI_DEMO_LLM_MODEL`, `ADAMI_DEMO_LLM_API_KEY` via a drop-in env file **not** in git
   - Required for live: `ADAMI_DEMO_LLM_ALLOWED_HOSTS` (comma-separated hostnames that must match the base URL host)
5. `systemctl enable --now adami-demo` (future operator action)

## Nginx (future task)

Use `deploy/nginx-adami-demo.conf.example` as a fragment:

- `proxy_pass http://127.0.0.1:8091/`
- `proxy_buffering off` for SSE
- `location = /api/demo/v1/internal/metrics { return 404; }`
- Inject `X-Adami-Client-IP $remote_addr` from the Nginx hop on loopback
- Never proxy `:8000` or `:8080`

Cloudflare / tunnel settings stay as they are until a dedicated follow-up.

## Health / smoke

- `curl -sS http://127.0.0.1:8091/v1/health` → `status` is `ok` / `degraded` / `unavailable`
- `POST /v1/session` with a allowed `Origin` sets `adami_demo_sid` and does **not** return a session id in JSON
- Fake LLM: `POST /v1/turns` returns `text/event-stream` with `accepted.mode=fake`

## Logs

- systemd: `journalctl -u adami-demo -n 80 --no-pager`
- Expect redacted errors; secrets and session ids must not appear in clear text

## Rollback

1. `systemctl stop adami-demo` (or disable the unit)
2. Remove the `/api/demo/` Nginx location
3. Static site remains up; production Kernel is unchanged

## Residual risks (operators)

- DNS rebinding: live mode refuses to start unless `ADAMI_DEMO_LLM_ALLOWED_HOSTS` is set and matches the base URL host
- Cookie `Path=/api/demo/` requires the public URL prefix to match
- In-memory sessions vanish on process restart
