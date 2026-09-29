from __future__ import annotations

import pytest

from agent.episode_contracts import (
    EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
)
from agent.episode_progress_adapters import progress_adapter, validate_progress_contract


def _contract():
    measure = NumericProgressMeasure(
        OpaqueId.mint("metric", "gates"), "Accepted gates", "normalized score",
        ProgressDirection.INCREASE, 0, EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER,
    )
    stop = ProgressStopCriteria(1, 0.1, 3)
    return measure, stop


def test_evidence_gate_adapter_is_host_only_and_normalized() -> None:
    measure, stop = _contract()
    adapter = validate_progress_contract(measure, stop, model_created=False)
    assert adapter.observed_value(0.5) == 0.5
    with pytest.raises(ValueError, match="host-only"):
        validate_progress_contract(measure, stop, model_created=True)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        progress_adapter(EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER).observed_value(1.1)
