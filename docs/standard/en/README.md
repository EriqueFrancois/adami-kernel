# AdamI Kernel

## Tagline

**An industrial event microkernel for a distributed digital organism — memory that persists, workflows that audit, and nerves that never block the brain.**

AdamI is not a thin wrapper around a single LLM API. It is a **long-horizon agent runtime**: sensory inputs converge on a typed event bus, a lifecycle-governed consumer applies **bounded concurrency** to decision processing, and orchestration persists DAG state so operations can survive restarts and scrutiny.

---

## Who this is for

- **Junior developers & integrators**: read Quickstart, then `docs/standard/en/API_REFERENCE.md`.
- **Press & analysts**: use this page + `WHITEPAPER.md` for positioning; cite architecture doc for technical depth.
- **Buyers (first-pass technical screen)**: verify claims in `ARCHITECTURE.md` and `SECURITY.md` against the open tree under `src/adami_kernel/`.

---

## Bio-inspired design (at a glance)

| Biological metaphor | Software counterpart | Role |
|---------------------|------------------------|------|
| **Nervous system (Nexus)** | `nexus/` — CLI shell, Telegram/Discord nerves, `EventBus` | Ingest stimuli, publish `AdamiEvent`, health & DLQ |
| **Cortex** | `cortex/` — router, intent, `DecisionProcessor`, prompts, tools | Reasoning, routing, delegation to planner |
| **Hippocampus** | `hippocampus/` — `LayeredMemory`, episodic memory, consolidation | SQLite-backed workflow state + append-only experience |
| **Circadian / organs** | `peripheral/` — e.g. scheduled training, report studio | Rhythmic housekeeping & outbound artifacts |
| **Immune system** | `guardian/` + `skill_manager` washers/loaders | AST audits, redaction, sandbox execution policy |

---

## Quickstart

### Kernel (Python)

```bash
poetry install
poetry run adami
```

- **Logs**: `.adami_data/kernel.log` (rotating; see `config.py`).
- **Persistent L2 memory**: `.adami_data/l2_memory.db`.
- **Secrets**: `.env` only; see `.env.example`.

### Web console (optional)

```bash
cd frontend
npm install
npm run dev
```

---

## “Performance” in the engineering sense

AdamI optimizes for **operational resilience**, not a single synthetic benchmark score:

- **Back-pressure on cognition**: `LifecycleManager` consumes `system.events` with a configurable **asyncio semaphore** cap (`ADAMI_EVENT_CONSUMER_MAX_CONCURRENT`) to prevent task storms.
- **Auditability**: `WorkflowEngine` persists `WorkflowState` via `LayeredMemory` — pause/resume and post-mortems are first-class.
- **Failure containment**: Event bus **DLQ** path and middleware ordering (sensitive filter + trace sink) reduce blast radius when a provider or tool misbehaves.

For module-specific SLAs and ops playbooks, see the existing `docs/` tree (e.g. dual-instance sync, DeerFlow bridge security, i18n policy).

---

## Next documents

- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **Business whitepaper**: [WHITEPAPER.md](WHITEPAPER.md)
- **API surface**: [API_REFERENCE.md](API_REFERENCE.md)
- **Security posture**: [SECURITY.md](SECURITY.md)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)

---

## License & attribution

See repository `LICENSE` / `pyproject.toml` authors field if present. This standardized pack describes the **current** open-source layout; deployment-specific tuning belongs in private runbooks.
