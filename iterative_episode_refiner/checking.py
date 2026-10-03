"""Connect an independently approved checking Episode to a target's typed return.

Both executions use the existing executor. The frozen instrument supplies the
checker and field mapping; neither candidate code nor a model chooses the oracle
after seeing a result. This module grants no artifact-body access or host tools.
"""

from dataclasses import dataclass

from agent.duet_contracts import FrozenDuetWorkflow, canonical_json
from episode_builder._contract_base import BuildReceipt
from episode_builder.store import BuildArtifactNotFoundError, BuildStoreCorruptionError
from episode_runtime.contracts import RunRegistration, RunTerminalStatus
from function_library.epistemic_contract import exact
from handoff_library import DuetLaunchAddress, admit_duet_launch_request

from .evaluation_inputs import workflow_template
from .records import Ref, pointer_parts, project


PAYLOAD_FIELDS = {"artifact_ids_by_role", "measurements", "states", "flags"}


@dataclass(frozen=True)
class CheckingPreparation:
    inputs: object = None
    launch: object = None
    gap: dict | None = None


def checker_definition(view, binding):
    instrument = view.data(Ref.from_record(binding["harness_ref"]))
    reference = instrument.get("checker_ref")
    if reference is None:
        return None
    definition = exact(
        view.data(Ref.from_record(reference)),
        {
            "workflow_ref",
            "build_receipt_ref",
            "authority_approval_ref",
            "launch_ref",
            "result_inputs",
        },
        "approved checking workflow",
    )
    if "instrument_return" in instrument:
        from .instrument_return import checker_from_return

        expected, _, _ = checker_from_return(view, instrument["instrument_return"])
        if canonical_json(definition) != canonical_json(expected):
            raise ValueError(
                "checking source differs from the accepted constructed build"
            )
    workflow = FrozenDuetWorkflow.from_record(
        view.data(Ref.from_record(definition["workflow_ref"]))
    )
    target = FrozenDuetWorkflow.from_record(
        view.data(Ref.from_record(view.contract.body["target_workflow_ref"]))
    )
    if workflow.artifact_id == target.artifact_id:
        raise ValueError(
            "independent checking cannot execute the target as its own oracle"
        )
    receipt = BuildReceipt.from_record(
        view.data(Ref.from_record(definition["build_receipt_ref"]))
    )
    if not receipt.materialized:
        raise ValueError("checking requires a separately admitted executable build")
    Ref.from_record(definition["authority_approval_ref"])
    template = workflow_template(
        workflow, view.data(Ref.from_record(definition["launch_ref"]))
    ).as_record()
    mappings = definition["result_inputs"]
    if not isinstance(mappings, (tuple, list)) or not mappings:
        raise ValueError(
            "checker must receive a declared projection of the target result"
        )
    destinations = set()
    for mapping in mappings:
        exact(mapping, {"field", "key", "result_path"}, "checker result input")
        field, key, path = mapping["field"], mapping["key"], mapping["result_path"]
        if field not in PAYLOAD_FIELDS or not isinstance(key, str) or not key:
            raise ValueError("checker input must name a typed payload field and key")
        if (field, key) in destinations or key in template[field]:
            raise ValueError(
                "checker result input duplicates or overwrites a frozen input"
            )
        # Paths are relative to the committed typed status, never raw audit logs.
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError(
                "checker result input requires a typed-result JSON pointer"
            )
        pointer_parts(path)
        destinations.add((field, key))
    return definition


def checker_launch(view, definition, typed_status, payload_contract, *, request_id):
    workflow = FrozenDuetWorkflow.from_record(
        view.data(Ref.from_record(definition["workflow_ref"]))
    )
    template = workflow_template(
        workflow, view.data(Ref.from_record(definition["launch_ref"]))
    ).as_record()
    for mapping in definition["result_inputs"]:
        template[mapping["field"]][mapping["key"]] = project(
            typed_status, mapping["result_path"]
        )
    address = DuetLaunchAddress(
        request_id, template["workflow_id"], template["goal_id"]
    )
    return admit_duet_launch_request(
        {**template, "request_id": request_id}, address, payload_contract
    )


def admitted_build(reader, definition, *, duet_id):
    """Read original approval/build evidence outside the campaign transaction."""
    receipt = BuildReceipt.from_record(
        reader.reference(Ref.from_record(definition["build_receipt_ref"]), duet_id)
    )
    inputs = reader.builds.inspection_inputs_for_receipt(receipt.receipt_id)
    workflow = reader.reference(Ref.from_record(definition["workflow_ref"]), duet_id)
    authority = reader.approval(Ref.from_record(definition["authority_approval_ref"]))
    if (
        inputs.receipt != receipt
        or not receipt.materialized
        or canonical_json(inputs.build_request.frozen_workflow.as_record())
        != canonical_json(workflow)
        or canonical_json(inputs.build_request.authority_approval.as_record())
        != canonical_json(authority)
    ):
        raise ValueError(
            "reference differs from its independently approved source build"
        )
    return inputs


def reference_definition(read_data, contract, binding):
    """Read-only evidence providers cannot be the source under refinement."""
    instrument = read_data(Ref.from_record(binding["harness_ref"]))
    if instrument.get("execution_kind") != "reference_workflow":
        return None
    exact(instrument, {"execution_kind", "reference_ref"}, "independent evidence route")
    definition = exact(
        read_data(Ref.from_record(instrument["reference_ref"])),
        {
            "workflow_ref",
            "build_receipt_ref",
            "authority_approval_ref",
            "launch_ref",
            "request_payload_contract_ref",
        },
        "independent evidence source",
    )
    for ref in definition.values():
        Ref.from_record(ref)
    workflow = FrozenDuetWorkflow.from_record(
        read_data(Ref.from_record(definition["workflow_ref"]))
    )
    editable = [contract.body["target_workflow_ref"]]
    manifest = contract.body.get("instrument_builds_ref")
    if manifest is not None:
        editable.extend(
            read_data(Ref.from_record(item["checker_ref"]))["workflow_ref"]
            for item in read_data(Ref.from_record(manifest))["builds"]
        )
    if any(workflow.artifact_id.value == ref["artifact_id"] for ref in editable):
        raise ValueError(
            "independent evidence cannot come from an editable target or checker"
        )
    receipt = BuildReceipt.from_record(
        read_data(Ref.from_record(definition["build_receipt_ref"]))
    )
    if not receipt.materialized:
        raise ValueError(
            "independent evidence requires an already admitted source build"
        )
    workflow_template(workflow, read_data(Ref.from_record(definition["launch_ref"])))
    read_data(Ref.from_record(definition["request_payload_contract_ref"]))
    return definition


def target_result(reader, binding, execution_ref):
    """Only an actual successful result of the already-bound candidate may flow in."""
    if "target_run_ref" in binding.body or "checking_gap" in binding.body:
        raise ValueError("a checking Run cannot substitute for the target Run")
    registration = RunRegistration.from_record(binding.body["registration"])
    evidence = reader.runs.read_evidence(registration.run_id)
    if (
        Ref(evidence.evidence_id, evidence.content_hash) != execution_ref
        or evidence.terminal_status is not RunTerminalStatus.SUCCEEDED
        or reader.runs.read_registration(registration.run_id) != registration
    ):
        raise ValueError("checker input lacks its exact successful target Run")
    terminal = next(
        event
        for event in reader.runs.read_audit_log(registration.run_id)
        if event.event_id == evidence.terminal_event_id
    )
    status = terminal.as_record()["payload"]["typed_status"]
    if canonical_json(status) != canonical_json(evidence.typed_status):
        raise ValueError("target evidence differs from its committed typed return")
    return status, evidence


def prepare_checking(
    reader, campaign_id, request_ref, target_binding, execution_ref, *, request_id
):
    """Resolve the next existing Run or an evidence-linked prerequisite gap.

    Corrupt target evidence and unexpected exceptions are not ordinary gaps.
    Known missing source/authority or incompatible typed inputs can be returned
    to the assigning parent without inventing an execution or verdict.
    """
    from .campaign_store import CampaignView

    with reader.duets.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        request = view.read(request_ref, "evaluation")
        definition = checker_definition(view, request.body)
    if definition is None:
        return None
    status, _ = target_result(reader, target_binding, execution_ref)
    prepared = prepare_checker_inputs(
        reader, campaign_id, definition, status, request_id=request_id
    )
    if prepared.gap is None:
        return prepared
    return CheckingPreparation(
        gap={
            **prepared.gap,
            "target_run_ref": target_binding.ref.as_record(),
            "target_execution_ref": execution_ref.as_record(),
        }
    )


def prepare_checker_inputs(
    reader, campaign_id, definition, typed_status, *, request_id
):
    """One checker preparation path for actual target results and named fixtures.

    Callers supply provenance: a target Run or an independently authorized
    control. A fixture is input data and must never be described as a target Run.
    """
    from .campaign_store import CampaignView

    with reader.duets.transaction() as connection:
        duet_id = CampaignView(connection, campaign_id).head["duet_id"]

    def unavailable(kind, detail):
        return CheckingPreparation(gap={"kind": kind, "detail": detail})

    try:
        inputs = admitted_build(reader, definition, duet_id=duet_id)
    except (BuildArtifactNotFoundError, ValueError) as exc:
        return unavailable("checker_source_unavailable", str(exc))
    except BuildStoreCorruptionError as exc:
        return unavailable("checker_source_invalid", str(exc))
    root = next(
        node for node in inputs.plan.nodes if node.local_id == inputs.plan.root_local_id
    )
    with reader.duets.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        try:
            launch = checker_launch(
                view,
                definition,
                typed_status,
                root.request_payload_contract,
                request_id=request_id,
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return unavailable("checker_input_invalid", str(exc))
    return CheckingPreparation(inputs=inputs, launch=launch)
