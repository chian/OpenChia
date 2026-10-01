"""Typed, instruction-free parent/child Episode handoffs."""

from .contracts import (
    ChildResult,
    DuetLaunchAddress,
    DuetLaunchRequest,
    HandoffPayloadContract,
    ParentRequest,
    ParentRequestAddress,
)
from .definitions import (
    ADMIT_CHILD_RESULT,
    ADMIT_DUET_LAUNCH_REQUEST,
    ADMIT_PARENT_REQUEST,
)
from .functions import (
    admit_child_result,
    admit_duet_launch_request,
    admit_parent_request,
)


__all__ = [
    "ADMIT_CHILD_RESULT",
    "ADMIT_DUET_LAUNCH_REQUEST",
    "ADMIT_PARENT_REQUEST",
    "ChildResult",
    "DuetLaunchAddress",
    "DuetLaunchRequest",
    "HandoffPayloadContract",
    "ParentRequest",
    "ParentRequestAddress",
    "admit_child_result",
    "admit_duet_launch_request",
    "admit_parent_request",
]
