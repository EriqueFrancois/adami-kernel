# Knowledge wiki narrative — SecondBrain vs stateless chat (AdamI)

**Audience**: operators and integrators who want a Karpathy-style “accumulating library” story grounded in this repository’s actual code paths.

**SSOT code**: `src/adami_kernel/hippocampus/second_brain.py` (`SecondBrainManager` class docstring and module constants). If this document disagrees with that file, trust the file.

---

## 1. Problem — stateless chat vs accumulating library

1. Stateless products treat each session as disposable: you type, you get an answer, you close the tab, and the system does not own a durable, structured store you control.
2. RAG-style flows re-discover fragments from uploads or corpora each time; they do not by themselves give you a **curated, interlinked vault** that grows under explicit rules.
3. The “LLM-Wiki” / librarian metaphor means: **knowledge compounds on disk** (or equivalent) with stable paths, summaries, and promotion rules—not only transient context windows.

AdamI’s file-backed **SecondBrain** (PARA-shaped tree under a configurable root) is the primary on-disk narrative for that accumulation. It is separate from but complementary to SQLite-backed **LayeredMemory** (workflow and system persistence).

---

## 2. AdamI stack — where the brain lives

1. **Manager**: `SecondBrainManager` in `src/adami_kernel/hippocampus/second_brain.py` bootstraps directories, seeds identity files, writes inbox/resource notes, and exposes retrieval helpers.
2. **Root path**: resolved from `settings.path_second_brain_root`, which defaults to data-relative `brain` unless overridden by environment **`ADAMI_SECOND_BRAIN_ROOT`** (see `path_second_brain_root` in `src/adami_kernel/config.py`).
3. **Doctrine**: the in-repo narrative for humans and L1 injection is `src/adami_kernel/SecondBrain.md` (loaded via `read_second_brain_doctrine` / `_SECOND_BRAIN_DOCTRINE_PATH` in the same module). Operational rules in the tree (for example `System/working-memory/OPERATING_RULES.md`) are part of runtime identity injection via `PromptBuilder` when wired through the kernel.

---

## 3. Layers — PARA layout and what code actually scans

1. **Bootstrapped top-level directories** (from `SecondBrainManager.dirs`): `Inbox`, `Projects`, `Areas`, `Resources`, `Archives`, `Identity`, `System/working-memory`. Together they form the PARA-style workspace the manager keeps alive.
2. **`retrieve_brain_snippets(topic, max_files)`** (same module): scans **only** top-level members of **`Inbox/`**, **`Projects/`**, and **`Resources/`**—constant `_RETRIEVE_SNIPPET_SUBDIRS` matches this. For each directory it considers **direct child** `*.md` files **excluding** `README.md`. Matching uses YAML frontmatter `summary`, the first Markdown `#` heading, path tokens, and the topic string; **no embeddings** (explicit in the method docstring).
3. **`search_similar_skill`** is a different path: recursive `*.py` / `*.md` under **`Resources/`** with overlap scoring for SkillFactory Tier3 fallback—do not confuse it with snippet retrieval coverage.

So: the “wiki” you get from `retrieve_brain_snippets` is **shallow** (one directory level in three folders), not whole-tree semantic search.

---

## 4. Promotion — candidates, Identity, and doctrine

1. **`System/working-memory/candidates.md`**: pool for observed preferences before promotion; aligned with the protocol described in `SecondBrain.md` (silent capture, user-triggered digest, promotion after confirmation).
2. **`Identity/`** files such as `TELOS.md`, `CONTEXT.md`, `PROFILE.md`: seeded by the manager; **Identity-level changes are approval-gated** in the doctrine—do not auto-rewrite TELOS without the human workflow the doctrine describes.
3. **Intake and moves**: `move_brain_note()` and ingest helpers keep paths inside the brain root; use these paths when tracing how multimodal or report output lands under `Inbox` or `Resources`.

This section is narrative alignment with `SecondBrain.md`; enforcement is split between prompts, hooks, and human process—not a single SQL constraint.

---

## 5. Not a full wiki yet — LayeredMemory and honest limits

1. **`LayeredMemory`** (`src/adami_kernel/hippocampus/layered_memory.py`) persists **workflow state**, experiences, checkpoints, and related domains in **`settings.path_l2_memory_db`** (SQLite under `.adami_data` by default). That is the durable **orchestration and episodic** plane, not the Markdown tree.
2. SecondBrain Markdown and LayeredMemory solve different problems: **files** for human-readable, diffable knowledge and reports; **database** for machine workflow graphs and high-volume traces.
3. AdamI does **not** currently promise automatic bi-directional wikilinks across every note, full-graph RAG over the entire PARA tree in one call, or Obsidian-native sync—those would be product extensions on top of this split.
4. Chroma / vector paths inside `LayeredMemory` are optional and dependency-gated; treat vector recall as **orthogonal** to `retrieve_brain_snippets` unless your deployment explicitly enables and tunes it.

---

## 6. Related reading

1. Technical topology: `docs/standard/en/ARCHITECTURE.md` (Hippocampus and event flow).
2. Chinese mirror (information-equivalent SSOT): [`docs/standard/zh/knowledge_wiki_second_brain.md`](../zh/knowledge_wiki_second_brain.md).

---

**Document baseline**: refresh SHA256 in `docs/internal/phase0_document_baseline.md` when this file is materially edited, or record the new hash in your PR description alongside Phase 0 fingerprints.
