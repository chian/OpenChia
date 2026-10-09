"""Advisory (non-blocking) findings on a Workflow Architecture.

Key Concept 12 (design deck; ADR 0003): Episodes are for work that needs
iterative refinement. Deterministic, one-shot work (a fixed list of calls, a
calculation) is a *tool* an Episode uses, not an Episode: its numerical
controller has no stopping decision to make. Nothing enforced this, and our own
bring-up Episode (two fixed GETs, "plan exhausted after unit 2") was one-shot.

These findings are advice for the Duet and the human. They are computed live
and never stored in the hash-bound draft record, so they do not change draft
readiness, approval or freezing.
"""

from __future__ import annotations

import re
from typing import Any

#: Phrases in an Episode's ``stopping`` or ``unit`` text that describe a fixed,
#: exhaustible plan rather than a decision driven by diminishing returns.
_FIXED_PLAN_PATTERNS = (
    ("fixed_plan", re.compile(r"\b(fixed|deterministic|predetermined)\b[^.]{0,60}\b(plan|list|sequence|set|units?|probes?|steps?|calls?)\b", re.I)),
    ("plan_exhausted", re.compile(r"\b(plan|list|queue|sequence)\b[^.]{0,40}\bexhaust", re.I)),
    # "one unit" describes a single iteration; a fixed count of several does not.
    ("counted_units", re.compile(r"\b(two|three|four|five|six|[2-9]|\d{2,})[- ](unit|step|probe|call)s?\b", re.I)),
    ("after_unit_n", re.compile(r"\bafter (the )?(unit|step|probe) ?\d+\b", re.I)),
    ("no_model_judgement", re.compile(r"\bno model (judg(e)?ment|decision)\b", re.I)),
)
#: Minimum number of distinct signals before an Episode is flagged.
_MIN_SIGNALS = 2


def _zero_continuation(contract) -> bool:
    continuation = getattr(getattr(contract, "numeric_control", None), "continuation", None)
    arguments = getattr(continuation, "arguments", None) or {}
    numbers = [value for value in dict(arguments).values() if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return bool(numbers) and all(value == 0 for value in numbers)


def one_shot_signals(contract) -> list[str]:
    """Which fixed-plan signals an Episode contract shows."""
    text = " ".join(str(getattr(contract, field, "") or "") for field in ("stopping", "unit"))
    signals = [name for name, pattern in _FIXED_PLAN_PATTERNS if pattern.search(text)]
    if _zero_continuation(contract):
        signals.append("zero_continuation_threshold")
    return signals


def workflow_advisories(workflow) -> list[dict[str, Any]]:
    """Advisory findings for a parsed ``EpisodeWorkflowSpec`` (empty when none)."""
    if workflow is None:
        return []
    findings = []
    for episode in workflow.episodes:
        signals = one_shot_signals(episode.contract)
        if len(signals) >= _MIN_SIGNALS:
            findings.append({
                "code": "episode_without_stopping_decision",
                "field_path": "stopping",
                "episode_local_id": episode.local_id,
                "blocking": False,
                "signals": signals,
                "detail": (
                    f"{episode.local_id}: the stopping rule describes a fixed, exhaustible plan, so the "
                    "numerical controller has no stopping decision to make. Key Concept 12 / ADR 0003: "
                    "one-shot, deterministic work is a tool step of an Episode that iterates, not an "
                    "Episode. Consider a tool (registered library function, brokered call, or CWL tool) "
                    "inside a parent Episode whose units have diminishing returns; approve as-is only "
                    "if this Episode is deliberate (e.g. a runtime probe)."
                ),
            })
    return findings


__all__ = ["one_shot_signals", "workflow_advisories"]
