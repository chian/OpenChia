"""Authorized checker source inside the same refinement candidate and history.

Namespaces separate build packages, not reasoning ownership. These helpers never
launch a Run, approve a workflow or turn edited checker source into an oracle.
"""

from dataclasses import dataclass

from agent.duet_contracts import canonical_json
from episode_builder._contract_base import BuildReceipt
from function_library.epistemic_contract import exact

from .materialization_edits import baseline_inputs, source_paths
from .records import Ref
from .checking import checker_descriptor


def _paths(reference, inputs):
    from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH

    prefix = f"__refinement_instruments/{reference.artifact_id.value}/"
    return {
        path: prefix + path
        for path in (*source_paths(
            inputs.build_request.frozen_workflow.workflow, inputs.plan
        ).values(), ENVIRONMENT_RECIPE_PATH)
    }


def _baseline(reader, duet_id, checker):
    checker_descriptor(checker)
    receipt = BuildReceipt.from_record(
        reader.reference(Ref.from_record(checker["build_receipt_ref"]), duet_id)
    )
    inputs = reader.builds.inspection_inputs_for_receipt(receipt.receipt_id)
    workflow = reader.reference(Ref.from_record(checker["workflow_ref"]), duet_id)
    approval = reader.approval(Ref.from_record(checker["authority_approval_ref"]))
    if (
        inputs.receipt != receipt
        or canonical_json(inputs.build_request.frozen_workflow.as_record())
        != canonical_json(workflow)
        or canonical_json(inputs.build_request.authority_approval.as_record())
        != canonical_json(approval)
    ):
        raise ValueError("instrument source differs from its approved build baseline")
    return inputs


def prepare_sources(store, duet_id, policy, target_workflow):
    """Only an explicit edit grant adds checker paths to initial campaign scope."""
    from .measure_needs import admission_policy, build_specification

    grant = admission_policy(policy)
    allowed = set(map(Ref.from_record, (grant or {}).get("instrument_build_refs", ())))
    requested = tuple(map(Ref.from_record, policy.get("editable_instrument_refs", ())))
    if len(set(requested)) != len(requested) or not set(requested) <= allowed:
        raise ValueError(
            "editable instruments must be unique authorized construction specifications"
        )
    records, files, writable = [], {}, []
    for reference in requested:
        spec = build_specification(
            lambda ref: store.evidence.reference(ref, duet_id), reference
        )
        checker = store.evidence.reference(
            Ref.from_record(spec["checker_ref"]), duet_id
        )
        inputs = _baseline(store.evidence, duet_id, checker)
        if (
            inputs.build_request.frozen_workflow.artifact_id
            == target_workflow.artifact_id
        ):
            raise ValueError("the target cannot be its own separately built instrument")
        handoff = store.evidence.materialization_handoff(
            inputs.receipt, inputs.build_request.frozen_workflow.duet_id.value
        )
        paths = _paths(reference, inputs)
        raw = handoff["candidate"]["files"]
        if not set(raw) <= set(paths):
            raise ValueError(
                "instrument handoff has source outside its approved workflow"
            )
        handoff_ref = store.put_data(
            duet_id, "instrument_materialization_handoff", handoff
        )
        materialization_ref = store.put_data(
            duet_id, "instrument_materialization", handoff["materialized_specification"]
        )
        records.append({
            "spec_ref": reference.as_record(),
            "checker_ref": spec["checker_ref"],
            "handoff_ref": handoff_ref.as_record(),
            "materialization_ref": materialization_ref.as_record(),
            "paths": paths,
        })
        files.update({paths[path]: digest for path, digest in raw.items()})
        writable.extend(paths.values())
    return records, files, writable


def entries(view):
    reference = view.contract.body.get("instrument_builds_ref")
    return view.data(Ref.from_record(reference))["builds"] if reference else ()


def initial_sources(reader, contract):
    """Validate initial auxiliary bytes against their original Builder records."""
    from .measure_needs import admission_policy, build_specification

    duet_id = contract.body["duet_id"]
    policy = reader.reference(
        Ref.from_record(contract.body["policy_bundle_ref"]), duet_id
    )
    requested_refs = tuple(
        map(Ref.from_record, policy.get("editable_instrument_refs", ()))
    )
    requested = set(requested_refs)
    grant = admission_policy(policy)
    authorized = set(
        map(Ref.from_record, (grant or {}).get("instrument_build_refs", ()))
    )
    reference = contract.body.get("instrument_builds_ref")
    builds = (
        reader.reference(Ref.from_record(reference), duet_id)["builds"]
        if reference
        else ()
    )
    if (
        len(requested_refs) != len(requested)
        or not requested <= authorized
        or {Ref.from_record(item["spec_ref"]) for item in builds} != requested
        or len(builds) != len(requested)
    ):
        raise ValueError(
            "instrument source manifest differs from the explicit edit grant"
        )
    files = {}
    for item in builds:
        exact(
            item,
            {"spec_ref", "checker_ref", "handoff_ref", "materialization_ref", "paths"},
            "instrument source namespace",
        )
        ref = Ref.from_record(item["spec_ref"])
        spec = build_specification(lambda ref: reader.reference(ref, duet_id), ref)
        if spec["checker_ref"] != item["checker_ref"]:
            raise ValueError("instrument source names a different checker")
        checker = reader.reference(Ref.from_record(item["checker_ref"]), duet_id)
        if checker["workflow_ref"] == contract.body["target_workflow_ref"]:
            raise ValueError("an auxiliary instrument cannot be the primary target")
        inputs = _baseline(reader, duet_id, checker)
        handoff = reader.materialization_handoff(
            inputs.receipt, inputs.build_request.frozen_workflow.duet_id.value
        )
        if (
            item["paths"] != _paths(ref, inputs)
            or canonical_json(
                reader.reference(Ref.from_record(item["handoff_ref"]), duet_id)
            )
            != canonical_json(handoff)
            or canonical_json(
                reader.reference(Ref.from_record(item["materialization_ref"]), duet_id)
            )
            != canonical_json(handoff["materialized_specification"])
        ):
            raise ValueError(
                "instrument baseline metadata differs from original source"
            )
        files.update({
            item["paths"][path]: digest
            for path, digest in handoff["candidate"]["files"].items()
        })
    return files


def selected_entry(view, binding):
    instrument = view.data(Ref.from_record(binding["harness_ref"]))
    if instrument.get("execution_kind") != "instrument_build":
        return None
    exact(
        instrument,
        {"execution_kind", "instrument_build_ref"},
        "instrument-build evaluation",
    )
    selected = [
        item
        for item in entries(view)
        if item["spec_ref"] == instrument["instrument_build_ref"]
    ]
    if len(selected) != 1:
        raise ValueError(
            "instrument build is outside the campaign's explicit edit grant"
        )
    return selected[0]


def is_primary_source(view, source):
    request = view.read(Ref.from_record(source.body["request_ref"]), "evaluation")
    instrument = view.data(Ref.from_record(request.body["harness_ref"]))
    return (
        instrument.get("execution_kind") == "target_workflow"
        and instrument.get("target_workflow_ref")
        == view.contract.body["target_workflow_ref"]
    )


def relevant_sources(view, bindings):
    """Source admission belongs to candidate bytes, not the requesting measure.

    Local repair must see an acceptance check's rejected build of the same
    candidate. Exact harness and capability references keep other instrument
    builds out; this does not reuse check outcomes or confer acceptance.
    """
    authorized = {
        (
            Ref.from_record(binding["harness_ref"]),
            Ref.from_record(binding["capability_ref"]),
        )
        for binding in bindings
    }
    sources = []
    for row in view.entries("evaluation_source"):
        if row.record.body["candidate_ref"] != view.candidate.ref.as_record():
            continue
        request = view.read(
            Ref.from_record(row.record.body["request_ref"]), "evaluation"
        )
        identity = (
            Ref.from_record(request.body["harness_ref"]),
            Ref.from_record(request.body["capability_ref"]),
        )
        if identity in authorized:
            sources.append(row)
    return sources


@dataclass(frozen=True)
class SourceScope:
    baseline: object
    paths: dict
    handoff: dict
    workflow_ref: dict
    approval_ref: dict
    instrument: dict | None = None
    fixed: bool = False


def source_scope(reader, contract, candidate, binding=None):
    """Resolve exact package bytes; no namespace is silently compiled as a target."""
    from .checking import admitted_build, reference_definition

    duet_id = contract.body["duet_id"]
    if binding is not None:
        definition = reference_definition(
            lambda ref: reader.reference(ref, duet_id), contract, binding
        )
        if definition is not None:
            inputs = admitted_build(reader, definition, duet_id=duet_id)
            root = next(
                node
                for node in inputs.plan.nodes
                if node.local_id == inputs.plan.root_local_id
            )
            if canonical_json(root.request_payload_contract) != canonical_json(
                reader.reference(
                    Ref.from_record(definition["request_payload_contract_ref"]), duet_id
                )
            ):
                raise ValueError(
                    "reference input schema differs from its admitted root interface"
                )
            return SourceScope(
                inputs,
                {},
                {},
                definition["workflow_ref"],
                definition["authority_approval_ref"],
                fixed=True,
            )
    reference = contract.body.get("instrument_builds_ref")
    builds = (
        reader.reference(Ref.from_record(reference), duet_id)["builds"]
        if reference
        else ()
    )
    auxiliary_paths = {path for item in builds for path in item["paths"].values()}
    instrument = (
        reader.reference(Ref.from_record(binding["harness_ref"]), duet_id)
        if binding
        else {}
    )
    if instrument.get("execution_kind") == "instrument_build":
        exact(
            instrument,
            {"execution_kind", "instrument_build_ref"},
            "instrument-build evaluation",
        )
        selected = [
            item
            for item in builds
            if item["spec_ref"] == instrument["instrument_build_ref"]
        ]
        if len(selected) != 1:
            raise ValueError("unapproved auxiliary build source")
        selected = selected[0]
        checker = reader.reference(Ref.from_record(selected["checker_ref"]), duet_id)
        inputs = _baseline(reader, duet_id, checker)
        paths = _paths(Ref.from_record(selected["spec_ref"]), inputs)
        if paths != selected["paths"]:
            raise ValueError("instrument namespace differs from its approved modules")
        handoff = reader.materialization_handoff(
            inputs.receipt, inputs.build_request.frozen_workflow.duet_id.value
        )
        if canonical_json(handoff) != canonical_json(
            reader.reference(Ref.from_record(selected["handoff_ref"]), duet_id)
        ):
            raise ValueError("instrument baseline handoff changed")
        return SourceScope(
            inputs,
            paths,
            handoff,
            checker["workflow_ref"],
            checker["authority_approval_ref"],
            selected,
        )
    if binding and (
        instrument.get("execution_kind") != "target_workflow"
        or instrument.get("target_workflow_ref") != contract.body["target_workflow_ref"]
    ):
        raise ValueError("source evaluation does not name an authorized build")
    inputs = baseline_inputs(reader, contract)
    paths = {
        path: path
        for path in source_paths(
            inputs.build_request.frozen_workflow.workflow, inputs.plan
        ).values()
    }
    from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH

    paths[ENVIRONMENT_RECIPE_PATH] = ENVIRONMENT_RECIPE_PATH
    if set(candidate.body["files"]) - set(paths) - auxiliary_paths:
        raise ValueError(
            "candidate contains source outside its declared build namespaces"
        )
    handoff = reader.materialization_handoff(inputs.receipt, duet_id)
    return SourceScope(
        inputs,
        paths,
        handoff,
        contract.body["target_workflow_ref"],
        contract.body["target_approval_ref"],
    )


def add_context(view, assignment, context):
    """Expose only relevant checker source contracts, not another shared prompt."""
    from .candidate_source import source_kind
    from .materialization_edits import edit_context
    from .instrument_return import return_context

    writable = set(assignment.body["writable_paths"])
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    selected = []
    for entry in entries(view):
        if not writable.intersection(entry["paths"].values()):
            continue
        handoff = view.data(Ref.from_record(entry["handoff_ref"]))
        plan_context = edit_context(view, policy, assignment, instrument=entry)
        selected.append({
            "spec_ref": entry["spec_ref"],
            "checker_ref": entry["checker_ref"],
            "paths": entry["paths"],
            "materialization_ref": entry["materialization_ref"],
            "candidate_materialization": plan_context,
        })
        for local_id, path in plan_context["source_paths"].items():
            context["source_kinds"][path] = source_kind(handoff, local_id)
    context["instrument_builds"] = selected
    context["instrument_returns"] = return_context(view, assignment)
