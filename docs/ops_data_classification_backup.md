# AdamI data tiers & backup (ops)

This note classifies on-disk AdamI state so backup and retention policies stay consistent with risk.

## Tier 0 — Secrets (never backup as plaintext in shared stores)

- **Content**: `.env`, any exported API tokens, `ADAMI_TASK_QUEUE_FERNET_KEY`, TLS material.
- **Backup**: secret manager / encrypted vault only; exclude from generic `tar` of the repo tree unless encrypted end-to-end.

## Tier 1 — Durable product state (highest restore priority)

- **Examples**: `l2_memory.db`, `graph_memory.db`, `vector_db/`, SecondBrain tree under `brain/`, `experience/`, policy `manifest.json`, `dlq.db` (replay semantics).
- **Backup**: frequent snapshots + integrity checks; test restore periodically.

## Tier 2 — Operational / ephemeral (recreate OK with bounded loss)

- **Examples**: `task_queue.json` (per-chat FIFO of **pending** CLI/Telegram/Discord tasks), idle caches, sandbox scratch under `sandbox_volume/`.
- **Semantics**: safe to truncate after incidents; TTL and `ADAMI_TASK_QUEUE_MAX_*` bound growth. Optional Fernet (`ADAMI_TASK_QUEUE_FERNET_KEY`) protects backlog text at rest.
- **Backup**: include in **short-retention** rolling snapshots if you need post-mortem of queued prompts; otherwise exclude to shrink backup size. If encrypted, rotate keys with a re-save window (old files unreadable without old key).

## Tier 3 — Rebuildable / cache

- **Examples**: `tmp_skills/`, `chroma` if reproducible from sources, MarkItDown caches when enabled.
- **Backup**: usually **exclude**; rebuild from pipelines.

## Suggested backup order (snapshot script)

1. Quiesce or accept small skew (queue file is atomically replaced).
2. Snapshot Tier 1 paths under `ADAMI_DATA_DIR` plus SecondBrain root.
3. Optionally add Tier 2 paths with shorter retention than Tier 1.
4. Never place Tier 0 files next to Tier 1 dumps without encryption.

## Related config (queue)

See `ADAMI_TASK_QUEUE_*` in `src/adami_kernel/config.py` and comments in `.env.example`.
