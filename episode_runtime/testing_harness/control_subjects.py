"""Grounded checker inputs as subjects of the shared experiment interface.

The campaign owns the case and its expected polarity. This projection grants
only execution of that exact declared checker dependency, not another Duet's
history, mutable criteria, or a separately managed control lifecycle.
"""

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json
from iterative_episode_refiner.campaign_store import CampaignView
from iterative_episode_refiner.checking import admitted_build, checker_payload
from iterative_episode_refiner.evidence import EvidenceReader
from iterative_episode_refiner.measure_controls import control_request
from iterative_episode_refiner.records import Ref

from ..records.experiments import read_reference, read_record
from ..scoped import FreshEntryScope
from .boundaries import fresh_entry_declaration
from .inputs import workflow_template


def control_subject(request, *, inputs, artifacts, builds, runs=None):
    """Validate a declared control without creating records or executing code."""
    reference = request["requirements"][0]["requirement_ref"]
    row = artifacts.get_artifact(reference["artifact_id"])
    if row is None or row["kind"] != "experiment.control_target.v1":
        return None
    owner = row["duet_id"]
    body = read_reference(artifacts, reference, owner)["record"]
    exact(
        body,
        {
            "campaign_ref",
            "proposal_ref",
            "grounding_ref",
            "control_ref",
            "build_receipt_ref",
            "scope",
        },
        "grounded control target",
    )
    contract = read_reference(artifacts, body["campaign_ref"], owner)["record"]
    reader = EvidenceReader(artifacts, builds, runs)
    with artifacts.transaction() as connection:
        view = CampaignView(connection, OpaqueId(contract["campaign_id"]))
        if view.contract.ref.as_record() != body["campaign_ref"]:
            raise ValueError("control subject changes the admitted campaign")
        owner_state = artifacts.get_duet(owner)
        if (
            owner_state is None
            or owner_state["authority_head_approval_id"]
            != view.contract.body["target_approval_ref"]["artifact_id"]
        ):
            raise ValueError(
                "control campaign no longer has its original target authority"
            )
        proposal, grounding, control, checker = control_request(
            view,
            *(
                Ref.from_record(body[field])
                for field in ("proposal_ref", "grounding_ref", "control_ref")
            ),
        )
        template = view.data(Ref.from_record(checker["launch_ref"]))
        environment = _thaw_json(view.contract.body["environment_ref"])
        selection = _thaw_json(
            view.data(Ref.from_record(proposal.body["decision_function_ref"]))
        )
    checker_inputs = admitted_build(reader, checker, duet_id=owner)
    receipt = {
        "artifact_id": checker_inputs.receipt.receipt_id.value,
        "content_hash": checker_inputs.receipt.content_hash.value,
    }
    if (
        inputs.receipt != checker_inputs.receipt
        or body["build_receipt_ref"] != receipt
        or request["build_receipt_ref"] != receipt
        or request["candidate_ref"] != receipt
        or request["campaign_ref"] != body["campaign_ref"]
        or request["environment_ref"] != environment
        or len(request["requirements"]) != 1
        or request["requirements"][0]["measure_ref"] != body["proposal_ref"]
    ):
        raise ValueError(
            "control experiment changes its exact checker, campaign, environment or proposed measure"
        )
    scope = FreshEntryScope.from_record(body["scope"])
    saved = read_reference(artifacts, _thaw_json(scope.boundary_ref), owner)
    if saved["kind"] != "experiment.fresh_entry_boundary.v1" or canonical_json(
        saved["record"]
    ) != canonical_json(scope.boundary):
        raise ValueError("control subject lost its committed fresh-entry boundary")
    declaration = fresh_entry_declaration(
        inputs, entry_local_id=checker["entry_local_id"]
    )
    scope_fields = {
        key: declaration.pop(key)
        for key in ("kind", "entry_local_id", "included_local_ids", "included_grains")
    }
    payload = checker_payload(inputs, checker, template, control["typed_status"])
    expected = {
        **declaration,
        "input_payload": payload,
        "definition_ref": _thaw_json(scope.boundary["definition_ref"]),
        "input_evidence_ref": body["control_ref"],
    }
    definition = read_reference(artifacts, expected["definition_ref"], owner)
    if canonical_json(definition["record"]) != canonical_json(
        checker
    ) or canonical_json(expected) != canonical_json(scope.boundary):
        raise ValueError(
            "control boundary differs from its independently grounded input or declared context"
        )
    if any(
        canonical_json(scope.as_record()[key]) != canonical_json(value)
        for key, value in scope_fields.items()
    ):
        raise ValueError("control boundary changes the admitted checker subtree")
    scope.validate_plan(inputs.plan)
    selected = request["scope"]
    if (
        any(
            selected[key] != scope_fields[key]
            for key in ("kind", "entry_local_id", "included_local_ids")
        )
        or selected["invocation_path"]
        or request["boundary"]
        != {"parent_context_ref": _thaw_json(scope.boundary_ref), "children": "execute"}
    ):
        raise ValueError(
            "control experiment must explicitly select its declared fresh checker entry and subtree"
        )
    start = request["start"]
    if start["kind"] == "saved_inputs":
        if start["artifact_ref"] != reference:
            raise ValueError(
                "saved control inputs must name this exact grounded control target"
            )
    elif start["kind"] == "fresh":
        if canonical_json(start["input_payload"]) != canonical_json(payload):
            raise ValueError(
                "fresh control inputs differ from the independent grounding"
            )
    else:
        raise ValueError(
            "a grounded control is not an interrupted-execution checkpoint"
        )
    source_owner = inputs.build_request.frozen_workflow.duet_id.value
    if request["recording_ref"] is not None:
        recording = read_reference(artifacts, request["recording_ref"], source_owner)
        if recording["kind"] != "experiment.recording.v1":
            raise ValueError("recorded control requires a shared Run recording")
        execution = read_record(
            artifacts,
            "execution",
            run_id=recording["record"]["registration_ref"]["run_id"],
        )
        if execution is None:
            raise ValueError("recorded control lacks shared execution evidence")
        source = read_reference(artifacts, execution["record"]["intent_ref"], owner)
        if (
            source["kind"] != "experiment.dispatch.v1"
            or source["record"]["spec"]["requirements"][0]["requirement_ref"]
            != reference
        ):
            raise ValueError(
                "recording belongs to another grounded control; checker dependency grants no general history access"
            )
    return {
        "kind": "grounded_control",
        "owner_duet_id": owner,
        "recording_owner_duet_id": source_owner,
        "reference": reference,
        "binding": body,
        "execution_scope": scope,
        "launch_template": workflow_template(inputs.build_request.frozen_workflow),
        "measurement": {
            "eligible": request["mode"] in {"live_fresh", "live_saved", "recorded"},
            "reasons": []
            if request["mode"] != "numerical"
            else ["This control requires checker execution, not numerical replay."],
            "implementation_ref": None,
            "criterion": {
                "requirement_key": grounding["requirement_key"],
                "predicate": selection,
                "observation_path": grounding["observation_path"].removeprefix(
                    "/payload/typed_status"
                ),
                "expected_value": _thaw_json(grounding["expected"]),
                "required_outcome": control["expected_outcome"],
                "limitations": [
                    "A correct grounded control validates this exact checker behavior, not the full measure or repaired target."
                ],
            },
        },
    }
