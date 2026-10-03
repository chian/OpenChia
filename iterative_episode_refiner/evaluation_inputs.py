"""Project frozen validation inputs through the existing root-launch contract.

An input reference names a complete DuetLaunchRequest, not instructions or a
second transport. Only the host's fresh request identity changes when launching
the candidate. Artifact IDs retain their existing runtime meaning; this module
does not grant artifact-store access to the target.
"""

from agent.duet_contracts import FrozenDuetWorkflow
from episode_runtime.testing.inputs import workflow_template
from handoff_library import (
    DuetLaunchAddress,
    admit_duet_launch_request,
)

from .records import Ref


def native_template(view, binding):
    """Validate input identity/types without depending on mutable Target Workflow code."""
    instrument = view.data(Ref.from_record(binding["harness_ref"]))
    from .instrument_builds import selected_entry
    from .checking import reference_definition

    entry = selected_entry(view, binding)
    reference = reference_definition(view.data, view.contract, binding)
    workflow_ref = view.contract.body["target_workflow_ref"]
    if reference is not None:
        workflow_ref = reference["workflow_ref"]
    elif entry is not None:
        checker = view.data(Ref.from_record(entry["checker_ref"]))
        workflow_ref = checker["workflow_ref"]
    elif (
        instrument.get("execution_kind") != "target_workflow"
        or instrument.get("target_workflow_ref")
        != view.contract.body["target_workflow_ref"]
    ):
        raise ValueError(
            "launch input requires an approved target, instrument-build or reference binding"
        )
    workflow = FrozenDuetWorkflow.from_record(view.data(Ref.from_record(workflow_ref)))
    references = binding["input_refs"]
    if not isinstance(references, (list, tuple)) or len(references) > 1:
        raise ValueError(
            "native validation accepts one complete launch input, not a batch or merged inputs"
        )
    template = (
        view.data(Ref.from_record(references[0]))
        if references
        else (
            view.data(Ref.from_record(reference["launch_ref"]))
            if reference is not None
            else None
        )
    )
    return workflow_template(workflow, template)


def native_launch(view, binding, payload_contract, *, request_id=None):
    """Re-admit the exact template against the candidate's actual root interface."""
    template = native_template(view, binding)
    address = DuetLaunchAddress(
        request_id=template.request_id if request_id is None else request_id,
        workflow_id=template.workflow_id,
        goal_id=template.goal_id,
    )
    return admit_duet_launch_request(
        {**template.as_record(), "request_id": address.request_id},
        address,
        payload_contract,
    )


def semantic_inputs(view, binding):
    """Input meaning for comparisons, never a replacement authorization record.

    Keep the original empty-input fact identities. A template's request ID and
    enclosing artifact identity do not make otherwise identical inputs novel.
    """
    if binding["harness_ref"] is None:
        return binding["input_refs"]
    try:
        if (
            not binding["input_refs"]
            and view.data(Ref.from_record(binding["harness_ref"])).get("execution_kind")
            != "reference_workflow"
        ):
            return []
        template = native_template(view, binding)
    except (ValueError, KeyError, TypeError):
        # Missing/unsupported instruments still need a parent decision context.
        # Preserve their exact references, without guessing semantic equivalence.
        # Availability/admission separately rejects them before observation.
        return binding["input_refs"]
    payload = {
        field: value
        for field, value in template.as_record().items()
        if field not in {"request_id", "workflow_id", "goal_id"}
    }
    return [payload] if any(payload.values()) else []


def instrument_context(view, binding):
    identity = binding["harness_ref"]
    if identity is not None:
        harness = view.data(Ref.from_record(identity))
        if "instrument_return" in harness:
            from .instrument_return import semantic_instrument

            identity = semantic_instrument(view, harness)
    return {
        "harness_ref": identity,
        "capability_ref": binding["capability_ref"],
        "input_refs": semantic_inputs(view, binding),
    }


def candidate_payload_contract(view, binding=None):
    from .materialization_edits import stored_plan
    from .instrument_builds import selected_entry
    from .checking import reference_definition

    reference = (
        reference_definition(view.data, view.contract, binding) if binding else None
    )
    if reference is not None:
        return view.data(Ref.from_record(reference["request_payload_contract_ref"]))
    entry = selected_entry(view, binding) if binding else None
    plan = stored_plan(view, view.candidate, instrument=entry)
    roots = [
        node for node in plan["nodes"] if node["local_id"] == plan["root_local_id"]
    ]
    if len(roots) != 1:
        raise ValueError("the candidate has no materialized root launch interface")
    return roots[0]["request_payload_contract"]
