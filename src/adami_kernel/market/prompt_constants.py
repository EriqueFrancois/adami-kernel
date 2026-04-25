"""Model-facing market / MetaCortex strings (English; not bound to UI locale)."""

from __future__ import annotations

GITHUB_KEYWORD_REFINE = """You are a GitHub search expert.
Extract the 2-4 most important ENGLISH keywords (total length strictly <= 60 characters) for repository search.
Return ONLY the keywords separated by spaces — no explanation, no quotes.

Task description:
{original_query}
"""

META_CORTEX_PERSONA = "Current system capability assessment"
