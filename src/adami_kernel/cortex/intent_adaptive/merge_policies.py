# src/adami_kernel/cortex/intent_adaptive/merge_policies.py
"""Multi-label family merge rules (Step 4.1); English reason_codes for telemetry."""

from __future__ import annotations

from typing import List

from adami_kernel.cortex.intent_adaptive.models import IntentClassificationResult, IntentFamily


def _ordered_unique_families(result: IntentClassificationResult) -> List[IntentFamily]:
    """Primary first, then ``family_candidates``, deduped by first occurrence."""
    seen: set[IntentFamily] = set()
    out: list[IntentFamily] = []
    for f in (result.primary_family, *result.family_candidates):
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def apply_family_merge_policy(
    result: IntentClassificationResult,
    *,
    action_permission_granted: bool = False,
) -> IntentClassificationResult:
    """
    Resolve ``family_candidates`` + ``primary_family`` conflicts.

    Rules (priority order):
    1. If ``system`` appears anywhere → ``primary_family=system``, clear candidates,
       ``route=dynamic``, append ``merge_family_system_wins``.
    2. Else if ``action`` appears:
       - When ``action_permission_granted`` is False → demote ``action``:
         if another family exists, first non-action becomes primary and ``route=clarify``;
         if only ``action`` → ``primary_family=unknown``, ``route=clarify``, append
         ``merge_action_rejected``.
       - When permission is True → keep model primary; only strip duplicate candidates.
    3. Else → drop candidates that duplicate ``primary_family`` only.
    """
    candidates = _ordered_unique_families(result)
    codes = list(result.reason_codes)

    if IntentFamily.SYSTEM in candidates:
        if result.primary_family != IntentFamily.SYSTEM:
            codes.append("merge_family_system_wins")
        return result.model_copy(
            update={
                "primary_family": IntentFamily.SYSTEM,
                "family_candidates": [],
                "route": "dynamic",
                "reason_codes": codes,
            }
        )

    if IntentFamily.ACTION in candidates:
        if action_permission_granted:
            fc = [f for f in result.family_candidates if f != result.primary_family]
            return result.model_copy(update={"family_candidates": fc})
        codes.append("merge_action_requires_permission")
        non_action = [c for c in candidates if c != IntentFamily.ACTION]
        if non_action:
            new_primary = non_action[0]
            rest = [c for c in non_action[1:] if c != new_primary]
            return result.model_copy(
                update={
                    "primary_family": new_primary,
                    "family_candidates": rest,
                    "route": "clarify",
                    "reason_codes": codes,
                }
            )
        return result.model_copy(
            update={
                "primary_family": IntentFamily.UNKNOWN,
                "family_candidates": [],
                "route": "clarify",
                "reason_codes": codes + ["merge_action_rejected"],
            }
        )

    fc = [f for f in result.family_candidates if f != result.primary_family]
    if fc != result.family_candidates:
        return result.model_copy(update={"family_candidates": fc})
    return result
