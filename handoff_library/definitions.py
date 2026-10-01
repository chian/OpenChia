"""Importable handoff function objects for Episode composition."""

from types import MappingProxyType

from function_library import FunctionImplementation, LibraryFunction


ADMIT_PARENT_REQUEST = LibraryFunction(
    library="handoff_library",
    function_id="admit_parent_request",
    interface="handoff.parent_request_admission",
    description=(
        "Admit one closed parent-to-child request against its exact invocation "
        "address and edge vocabulary."
    ),
    implementation=FunctionImplementation(
        module="handoff_library.functions",
        symbol="admit_parent_request",
        is_async=False,
    ),
    input_type=(
        "mapping, ParentRequestAddress, and edge-local HandoffPayloadContract"
    ),
    output_type="handoff_library.ParentRequest",
    effect="Pure validation and immutable projection.",
    failure_contract=(
        "Rejects unknown fields, cross-wired identities or interfaces, and "
        "undeclared edge vocabulary."
    ),
    provenance=MappingProxyType({"owner": "handoff_library"}),
)


ADMIT_CHILD_RESULT = LibraryFunction(
    library="handoff_library",
    function_id="admit_child_result",
    interface="handoff.child_result_admission",
    description=(
        "Admit one closed child result against its exact request, declared "
        "result channels, and edge vocabulary."
    ),
    implementation=FunctionImplementation(
        module="handoff_library.functions",
        symbol="admit_child_result",
        is_async=False,
    ),
    input_type=(
        "mapping, admitted ParentRequest, declared channel IDs, and "
        "edge-local HandoffPayloadContract"
    ),
    output_type="handoff_library.ChildResult",
    effect="Pure validation and immutable projection.",
    failure_contract=(
        "Rejects unknown fields, replayed or cross-wired results, missing "
        "channels, and undeclared edge vocabulary."
    ),
    provenance=MappingProxyType({"owner": "handoff_library"}),
)


ADMIT_DUET_LAUNCH_REQUEST = LibraryFunction(
    library="handoff_library",
    function_id="admit_duet_launch_request",
    interface="handoff.duet_launch_admission",
    description=(
        "Admit one closed Duet-to-root launch request against its approved "
        "runtime address and root-edge vocabulary."
    ),
    implementation=FunctionImplementation(
        module="handoff_library.functions",
        symbol="admit_duet_launch_request",
        is_async=False,
    ),
    input_type=(
        "mapping, DuetLaunchAddress, and root-edge HandoffPayloadContract"
    ),
    output_type="handoff_library.DuetLaunchRequest",
    effect="Pure validation and immutable projection.",
    failure_contract=(
        "Rejects unknown fields, cross-wired launch identities, and undeclared "
        "root-edge vocabulary."
    ),
    provenance=MappingProxyType({"owner": "handoff_library"}),
)


__all__ = [
    "ADMIT_CHILD_RESULT",
    "ADMIT_DUET_LAUNCH_REQUEST",
    "ADMIT_PARENT_REQUEST",
]
