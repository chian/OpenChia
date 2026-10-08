"""Return a checked build to measure admission without changing active criteria.

The existing parent report, source admission and independent verification are
the handoff. Derived descriptors pin that build; they are not adequacy verdicts.
"""

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json
from function_library.refinement_contract import ROLE_SPECIALIZATION

from .instrument_builds import entries, selected_entry
from .grounding import authorize_acquisitions
from .measure_needs import build_specification
from .records import Ref


def _verification_owner(view, invocation):
    """Original observations may be returned by nested Verification Parts."""
    current = invocation
    while ROLE_SPECIALIZATION[current.record.body["role"]] == "verify":
        if current.status not in {"returned", "superseded"}:
            return None
        parent_ref = current.record.body["parent_assignment_ref"]
        parent = view.read(Ref.from_record(parent_ref), "assignment")
        if ROLE_SPECIALIZATION[parent.body["role"]] != "verify":
            return parent_ref
        matches = [entry for entry in view.entries("invocation") if entry.record.ref == parent.ref]
        if len(matches) != 1:
            return None
        current = matches[0]
    return None


def _accepted_sources(view, report, spec, spec_ref):
    assignment = view.read(Ref.from_record(report.body["assignment_ref"]), "assignment")
    required = {
        row.key: row.record
        for row in view.entries("check")
        if row.record.body["measure_ref"] == spec["acceptance_measure_ref"]
        and row.record.body["purpose"] == "acceptance"
        and row.record.body["mandatory"]
        and row.record.body["requirement_key"] in spec["requirement_keys"]
    }
    if {check.body["requirement_key"] for check in required.values()} != set(
        spec["requirement_keys"]
    ):
        raise ValueError("constructed instrument lacks its required acceptance checks")
    judged_keys = set(required)
    pending = list(required.values())
    while pending:
        for key in pending.pop().body["guard_keys"]:
            if key not in required:
                required[key] = view.entry("check", key).record
                pending.append(required[key])
    determinations = {item["check_key"]: item for item in report.body["determinations"]}
    sources = {}
    for key, check in required.items():
        determination = determinations.get(key)
        if (
            determination is None
            or determination["outcome"] != "pass"
            or determination["observation_ref"] is None
        ):
            raise ValueError(
                "constructed instrument has an unpassed acceptance check or guard"
            )
        observation = view.read(
            Ref.from_record(determination["observation_ref"]), "observation"
        )
        request = view.read(
            Ref.from_record(observation.body["request_ref"]), "evaluation"
        )
        verifier = view.entry("invocation", observation.invocation_id.value)
        if (
            observation.body["outcome"] != "pass"
            or observation.body["check_key"] != key
            or request.body["candidate_ref"] != report.body["selected_candidate_ref"]
            or check.body["environment_ref"] != view.contract.body["environment_ref"]
            or verifier.status not in {"returned", "superseded"}
            or ROLE_SPECIALIZATION[verifier.record.body["role"]] != "verify"
            or _verification_owner(view, verifier) != assignment.ref.as_record()
        ):
            raise ValueError(
                "instrument acceptance lacks its own independent Verify return"
            )
        if key not in judged_keys:
            continue
        selected = selected_entry(view, request.body)
        if (
            selected is None
            or selected["spec_ref"] != spec_ref
            or request.body["measure_ref"] != spec["acceptance_measure_ref"]
            or request.body["purpose"] != "acceptance"
        ):
            raise ValueError("instrument acceptance evaluated a different build")
        source = view.entry("evaluation_source", request.artifact_id.value)
        if (
            source.status != "admitted"
            or source.record.body["candidate_ref"]
            != report.body["selected_candidate_ref"]
        ):
            raise ValueError(
                "instrument acceptance has no exact admitted candidate source"
            )
        sources[source.record.ref] = source.record
    return sources


def checker_from_return(view, selection, requester=None):
    """Reconstruct the descriptor from original records, never a child summary."""
    exact(
        selection,
        {"spec_ref", "report_ref", "source_ref"},
        "constructed instrument return",
    )
    matches = [
        item for item in entries(view) if item["spec_ref"] == selection["spec_ref"]
    ]
    if len(matches) != 1:
        raise ValueError(
            "instrument return lacks the campaign's exact construction grant"
        )
    entry = matches[0]
    spec = build_specification(view.data, Ref.from_record(selection["spec_ref"]))
    report_ref = Ref.from_record(selection["report_ref"])
    report = view.entry("report", report_ref.artifact_id.value).record
    assignment = view.read(Ref.from_record(report.body["assignment_ref"]), "assignment")
    invocation = view.entry("invocation", report.invocation_id.value)
    if (
        report.ref != report_ref
        or invocation.record.ref != assignment.ref
        or invocation.status not in {"returned", "superseded"}
        or assignment.body["role"] != "designer"
        or report.body["termination"] != "attained"
        or assignment.body["acceptance_measure_ref"] != spec["acceptance_measure_ref"]
        or not set(spec["requirement_keys"])
        <= set(assignment.body["contribution_requirement_keys"])
        or any(
            conflict.body["state"] == "decision_required"
            and set(conflict.body["requirement_keys"]).intersection(
                spec["requirement_keys"]
            )
            for ref in report.body["conflict_refs"]
            for conflict in (view.read(Ref.from_record(ref), "conflict"),)
        )
    ):
        raise ValueError(
            "instrument construction has not returned an independently accepted design"
        )
    if requester is not None:
        from .measures import _within_owner

        if not _within_owner(view, assignment.body["parent_assignment_ref"], requester):
            raise ValueError(
                "instrument return is outside the requester's owning branch"
            )
    source_ref = Ref.from_record(selection["source_ref"])
    sources = _accepted_sources(view, report, spec, selection["spec_ref"])
    if source_ref not in sources:
        raise ValueError(
            "instrument return source was not independently accepted in this report"
        )
    source = sources[source_ref]
    definition = _thaw_json(view.data(Ref.from_record(entry["checker_ref"])))
    definition["build_receipt_ref"] = source.body["build_receipt_ref"]
    return definition, spec, entry


def _construction_grounding(view, spec, body):
    """Every acquired case must follow a route frozen in this construction spec."""
    acquired = authorize_acquisitions(view, body)
    required_routes = set(map(Ref.from_record, spec.get("acquisition_refs", ())))
    if set(acquired.acquisition_refs) != required_routes or len(
        acquired.acquisition_refs
    ) != len(required_routes):
        raise ValueError(
            "constructed measure must retain exactly its authorized acquisition routes"
        )
    required_cases = set(map(Ref.from_record, spec["grounding_refs"])) | set(
        acquired.case_refs
    )
    if set(map(Ref.from_record, body["grounding_refs"])) != required_cases:
        raise ValueError(
            "constructed measure must retain its full independently grounded case set"
        )
    for field in ("positive_control_refs", "negative_control_refs"):
        required = set(map(Ref.from_record, spec[field]))
        required.update(
            Ref.from_record(ref)
            for case_ref in acquired.case_refs
            for ref in view.data(case_ref)[field]
        )
        if not required or set(map(Ref.from_record, body[field])) != required:
            raise ValueError(
                f"constructed measure changes its independently authorized {field}"
            )


def prepare_return(session, assignment, selection, instrument, *, acquisition_refs=()):
    """Persist only reference data; ordinary measure admission owns authority."""
    with session.view() as view:
        checker, spec, _ = checker_from_return(view, selection, assignment)
        _construction_grounding(
            view,
            spec,
            {
                **instrument,
                "assignment_ref": assignment.ref.as_record(),
                "grounding_acquisition_refs": acquisition_refs,
            },
        )
        harnesses = {}
        for reference in instrument["grounding_refs"]:
            case = view.data(Ref.from_record(reference))
            ref = Ref.from_record(case["execution_binding"]["harness_ref"])
            harness = view.data(ref)
            if (
                harness.get("checker_ref") != spec["checker_ref"]
                or "instrument_return" in harness
            ):
                raise ValueError(
                    "construction cannot replace an unrelated or already revised oracle"
                )
            harnesses[ref] = harness
    checker_ref = session.put_data("constructed_checker", checker)
    revisions = []
    for ref, harness in sorted(
        harnesses.items(), key=lambda pair: pair[0].artifact_id.value
    ):
        revised = session.put_data(
            "constructed_checking_instrument",
            {
                **harness,
                "checker_ref": checker_ref.as_record(),
                "instrument_return": selection,
            },
        )
        revisions.append({
            "baseline_ref": ref.as_record(),
            "revised_ref": revised.as_record(),
        })
    return session.put_data(
        "instrument_return",
        {
            **selection,
            "checker_ref": checker_ref.as_record(),
            "harness_revisions": revisions,
        },
    )


def admitted_return(view, proposal):
    """Validate the proposed substitution without revising any grounded criterion."""
    reference = proposal.body.get("instrument_return_ref")
    if reference is None:
        return None
    bundle = exact(
        view.data(Ref.from_record(reference)),
        {
            "spec_ref",
            "report_ref",
            "source_ref",
            "checker_ref",
            "harness_revisions",
        },
        "constructed measure source",
    )
    selection = {key: bundle[key] for key in ("spec_ref", "report_ref", "source_ref")}
    requester = view.read(
        Ref.from_record(proposal.body["assignment_ref"]), "assignment"
    )
    checker, spec, _ = checker_from_return(view, selection, requester)
    if canonical_json(
        view.data(Ref.from_record(bundle["checker_ref"]))
    ) != canonical_json(checker):
        raise ValueError(
            "constructed checker changes more than its accepted source receipt"
        )
    if (
        proposal.body["oracle_kind"] != "independent_execution"
        or proposal.body["oracle_ref"] != spec["checker_ref"]
    ):
        raise ValueError(
            "constructed source requires its original independent oracle and executable controls"
        )
    if proposal.body["purpose"] != spec["purpose"]:
        raise ValueError("constructed instrument cannot change its authorized purpose")
    if set(proposal.body["requirement_keys"]) != set(spec["requirement_keys"]):
        raise ValueError("constructed measure changes its authorized requirements")
    _construction_grounding(view, spec, proposal.body)
    if not {canonical_json(ref) for ref in spec["limitation_refs"]} <= {
        canonical_json(ref) for ref in proposal.body["limitation_refs"]
    }:
        raise ValueError("constructed measure drops the instrument's limitations")
    revisions = {}
    for row in bundle["harness_revisions"]:
        exact(row, {"baseline_ref", "revised_ref"}, "constructed instrument binding")
        original_ref = Ref.from_record(row["baseline_ref"])
        original = view.data(original_ref)
        revised = view.data(Ref.from_record(row["revised_ref"]))
        if (
            original_ref in revisions
            or original.get("checker_ref") != spec["checker_ref"]
            or "instrument_return" in original
        ):
            raise ValueError(
                "constructed binding repeats or changes the original checker"
            )
        if canonical_json(revised) != canonical_json({
            **original,
            "checker_ref": bundle["checker_ref"],
            "instrument_return": selection,
        }):
            raise ValueError(
                "constructed binding changes frozen target inputs or capabilities"
            )
        revisions[original_ref] = row["revised_ref"]
    required = {
        Ref.from_record(
            view.data(Ref.from_record(ref))["execution_binding"]["harness_ref"]
        )
        for ref in proposal.body["grounding_refs"]
    }
    if set(revisions) != required:
        raise ValueError(
            "constructed binding must cover exactly the original complete cases"
        )
    return bundle["checker_ref"], revisions, spec["limitation_refs"]


def return_evidence(view, proposal):
    reference = proposal.body.get("instrument_return_ref")
    if reference is None:
        return ()
    bundle = view.data(Ref.from_record(reference))
    return (
        Ref.from_record(reference),
        *(
            Ref.from_record(bundle[field])
            for field in ("spec_ref", "report_ref", "source_ref")
        ),
    )


def return_context(view, requester):
    """Offer exact returned sources; no summaries or model-awarded acceptance."""
    if ROLE_SPECIALIZATION[requester.body["role"]] not in {"designer", "measure"}:
        return []
    result = []
    requirements = set(requester.body["contribution_requirement_keys"])
    for entry in entries(view):
        spec = build_specification(view.data, Ref.from_record(entry["spec_ref"]))
        if not set(spec["requirement_keys"]) <= requirements:
            continue
        for row in reversed(view.entries("report")):
            report = row.record
            if (
                report.body["role"] != "designer"
                or report.body["termination"] != "attained"
            ):
                continue
            try:
                sources = _accepted_sources(view, report, spec, entry["spec_ref"])
                for source in sources.values():
                    selection = {
                        "spec_ref": entry["spec_ref"],
                        "report_ref": report.ref.as_record(),
                        "source_ref": source.ref.as_record(),
                    }
                    checker_from_return(view, selection, requester)
                    result.append(selection)
                    break
                else:
                    continue
                break
            except ValueError:
                # Most reports concern the target or another checking task. They
                # are not candidates; their original findings remain in history.
                continue
    return result


def semantic_instrument(view, harness):
    """Rebuilding identical source cannot make the same adequacy claim novel."""
    from .materialization_edits import stored_plan

    selection = harness["instrument_return"]
    _, _, entry = checker_from_return(view, selection)
    source = view.read(Ref.from_record(selection["source_ref"]), "evaluation_source")
    candidate = view.read(Ref.from_record(source.body["candidate_ref"]), "candidate")
    plan = stored_plan(view, candidate, instrument=entry)
    checker = view.data(Ref.from_record(harness["checker_ref"]))
    return {
        **{
            key: value
            for key, value in harness.items()
            if key not in {"checker_ref", "instrument_return"}
        },
        "checker": {
            key: value for key, value in checker.items() if key != "build_receipt_ref"
        },
        "source": {
            original: candidate.body["files"][path]
            for original, path in entry["paths"].items()
        },
        "plan": {
            key: plan.get(key)
            for key in (
                "workflow_hash",
                "root_local_id",
                "nodes",
                "edges",
                "repeatable_calls",
            )
        },
    }
