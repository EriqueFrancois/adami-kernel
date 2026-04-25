"""Model-facing planner strings (English; not bound to UI locale).

Used for LLM prompts and injected context blocks. Product policy: keep these in
English so model behavior stays stable across ``ADAMI_UI_LOCALE``.
"""

from __future__ import annotations

# --- Digest follow-up task (published to system.events) ---
DIGEST_NOTE_TASK = """[digest this note] Turn the following SecondBrain note into reusable structured knowledge.
Output requirements:
1) 5-10 bullet points (one sentence each)
2) Actionable checklist (up to 8 items, with priority)
3) Risks/uncertainties (up to 5 items)
4) Three follow-up research questions

Source: {source}
note_path: {note_path}
note_uri: {uri}

[Note body]
{body}
""".strip()

EMPTY_NOTE_BODY = "(read failed or empty)"

# --- Injected into planner LLM context (SkillRouter path) ---
BRAIN_SNIPPETS_BLOCK = "SecondBrain snippets (Resources-related):\n{snippets}\n\n"

ANTHROPIC_SKILL_WRAPPER = """You will follow this workflow skill to shape your answer. Strictly follow its steps, structure, and output format.

Skill name: {skill_name}
Required parameters (infer from the task when possible): {required_params}

SKILL.md template:
{prompt_template}

{intent_meta_block}{brain_block}User task:
{task}
"""

# --- Legacy plan generator (JSON-only contract) ---
GENERATE_PLAN_PROMPT = """You must return ONLY valid JSON with no prose before or after.
{preamble}{intent_meta_block}{tools_section}

When creating a skill, you **must** put a full ```python fenced code block OUTSIDE the JSON.
Never put executable code inside JSON args.

Task:
{task}

Return shape:
{{
  "steps": [
    {{"action": "WEB_SEARCH", "args": {{"query": "2026 AI news"}}}},
    {{"action": "SUMMARIZE", "args": {{"count": 3}}}}
  ]
}}
"""

TOOLS_SECTION_TRUNCATED_SUFFIX = "\n... (tool list truncated)"

BUILTIN_SUMMARIZE_PROMPT = (
    "Produce exactly 3 concise bullets in the same language as the input. "
    "Each bullet at most 50 characters:\n{text}"
)

NO_TEXT_FALLBACK = "(no text)"

# --- Multi-agent DAG task descriptions (English; model-bound) ---
MULTI_AGENT_ENGINEER_DESCRIPTION = (
    "Based on research outputs, generate skill code only (do not execute it)."
)
MULTI_AGENT_EXECUTOR_DESCRIPTION = "Execute the skill produced by Engineer and return the result."
MULTI_AGENT_CRITIC_DESCRIPTION = "Review Engineer's outputs and the execution result."
MULTI_AGENT_EXECUTOR_EXISTING = "Execute existing skill {skill_name}."
MULTI_AGENT_CRITIC_REVIEW_EXECUTION = "Review execution results."
