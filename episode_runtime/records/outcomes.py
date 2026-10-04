"""Requirement judgments shared by experiments and refinement reports.

An outcome describes the tested candidate, not whether the evidence still
applies to a later revision. Its containing report owns that distinction.
Predictions are nullable for existing checks that recorded none; newly designed
experiments still require them in ExperimentInput.
"""

from typing import Annotated, Literal

from pydantic import JsonValue, StringConstraints

from .runs import EvidenceReference, RecordModel


Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class RequirementOutcome(RecordModel):
    requirement_ref: EvidenceReference
    requirement_key: Text | None = None
    measure_ref: EvidenceReference
    predicted: Text | None
    falsifying: Text | None
    status: Literal[
        "pass", "fail", "inconclusive", "error", "blocked", "not_applicable", "unavailable"
    ]
    observed: JsonValue
    criterion_expected: JsonValue
    evidence_ref: EvidenceReference | None
    reason: str | None
    limitations: list[str]
