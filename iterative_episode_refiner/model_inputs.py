"""Deliver the working inputs declared by each refinement Episode.

Stored reports have a separate audit body. Only their caller-requested return
values cross into reasoning. These projections do not change credit, evidence,
candidate admission, or continuation.
"""

from collections import Counter

from function_library.models import _thaw_json
from function_library.refinement_contract import INPUT_MEASUREMENTS, MODEL_INPUT_COMPONENTS

from .assignment_choices import assigned_addresses
from .model_history import iteration_history
from .records import Ref
from .report_contract import (
    _measurement, assigned_return_contract, requirement_address, requirement_catalog,
)
from .reports import parent_report, report_overview


def _measurements(session, view, call):
    from .judgment import judgment_purpose
    from .evaluation_plan import evaluation_availability, resolve_evaluations
    from .measures import implementation_covered_requirements

    assignment = call.assignment
    report = parent_report(view, call.invocation_id)
    catalog = requirement_catalog(view)
    role = assignment.body["role"]
    purposes = INPUT_MEASUREMENTS[role] or (judgment_purpose(view, assignment),)
    requirements = assigned_addresses(session, assignment)
    preservation = [
        address for address in assigned_addresses(session, assignment, "preservation_requirement_keys")
        if address not in requirements
    ]
    # A descendant inherits the wider scope for regression protection. Its own
    # work remains the parent's selected contribution, not that entire scope.
    measurements = {
        name: {
            purpose: _measurement(view, assignment, report.body, {
                "purpose": purpose, "requirements": addresses,
            }, catalog)
            for purpose in purposes
        }
        for name, addresses in (
            ("measurements", requirements),
            ("preservation_measurements", preservation),
        )
    }
    availability = evaluation_availability(resolve_evaluations(
        view, session.policy, assignment, judgment_purpose(view, assignment)
    ))
    result = {
        **measurements,
        "iteration_history": iteration_history(session, view, call),
        "evaluation_availability": {
            "executable": availability["executable"],
            "gaps": [{
                "kind": gap["kind"], "detail": gap["detail"],
                "requirements": [requirement_address(catalog[key]) for key in gap["requirement_keys"]],
            } for gap in availability["gaps"]],
        },
    }
    if role in {"parts", "designer"}:
        selected = set(assignment.body["contribution_requirement_keys"])
        covered = implementation_covered_requirements(
            view, assignment, assignment.body["local_measure_ref"], session.policy
        )
        result["implementation_measure_coverage"] = {
            "all_contribution_requirements_covered": selected <= covered,
            "covered_requirements": sorted(
                requirement_address(catalog[key]) for key in selected & covered
            ),
            "missing_requirements": sorted(
                requirement_address(catalog[key]) for key in selected - covered
            ),
            "meaning": (
                "Implementation-plan admission requires an authorized mandatory local "
                "check for every selected contribution requirement, bound to this "
                "local measure and environment. Check outcomes appear separately in "
                "measurements.local; independent acceptance has its own measure. "
                "Parts can stage a contribution covered by existing local checks "
                "while establishing checks for the broader requirements."
            ),
        }
    return result


def _coordination(session, view, call):
    from .coordination import relevant_conflicts

    catalog = requirement_catalog(view)
    return {"coordination": [{
        "kind": row.body["kind"], "state": row.body["state"],
        "requirements": [requirement_address(catalog[key]) for key in row.body["requirement_keys"]],
    } for row in relevant_conflicts(view, call.assignment)]}


def _prerequisites(session, view, call):
    """Pass the assigned need and the information its originating caller requested."""
    from .report_contract import _decision_need

    goal = view.data(Ref.from_record(call.assignment.body["goal_record_ref"]))
    catalog = requirement_catalog(view)
    result = []
    for reference in goal.get("prerequisite_refs", ()):
        need = view.read(Ref.from_record(reference), "measure_prerequisite")
        reports = [row.record for row in view.entries("report")
                   if row.record.invocation_id == need.invocation_id]
        result.append({
            **_decision_need(view, need, catalog)[0],
            "returned_information": report_overview(reports[-1]) if reports else None,
        })
    return {"assigned_prerequisites": result}


def _materialization(session, view, call):
    from .instrument_builds import add_context
    from .materialization_edits import edit_context

    context = {
        "candidate_materialization": edit_context(view, session.policy, call.assignment),
        "source_kinds": {},
    }
    add_context(view, call.assignment, context)
    if call.assignment.body["role"] == "measure":
        from .materialization_edits import stored_plan

        context["checking_target_materialization"] = stored_plan(view, view.candidate)
    return context


def _source(session, view, call):
    from .candidate_source import source_kind
    from .materialization_edits import edit_context
    from .measures import authorized_check_refs

    candidate = view.candidate
    readable = set(call.assignment.body["writable_paths"])
    if call.assignment.body["role"] == "measure":
        parent = view.read(Ref.from_record(call.assignment.body["parent_assignment_ref"]), "assignment")
        readable.update(parent.body["writable_paths"])
    for reference in authorized_check_refs(view, session.policy, call.assignment):
        check = view.read(reference, "check")
        if check.body["requirement_key"] in call.assignment.body["scope_requirement_keys"]:
            readable.update(check.body["dependency_paths"] or ())
    paths = readable & set(candidate.body["files"])
    files = {path: session.store.evidence.builds.read_blob(candidate.body["files"][path]).decode("utf-8")
             for path in sorted(paths)}
    edits = edit_context(view, session.policy, call.assignment)
    return {
        "source_files": files,
        "source_kinds": {path: source_kind(session.materialization_handoff, local_id)
                         for local_id, path in edits["source_paths"].items() if path in files},
    }


def _environment(session, view, call):
    from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH
    from .candidate_environment import findings

    paths = [path for path in call.assignment.body["writable_paths"]
             if path == ENVIRONMENT_RECIPE_PATH or path.endswith("/" + ENVIRONMENT_RECIPE_PATH)]
    return {"target_environment": {
        **session.evaluations.environment_context(),
        "recipe_paths": paths,
        "recipe_format": {
            "schema_version": 1, "python": "available runtime major.minor",
            "dependencies": ["registry requirement with exact version or lower and upper bounds"],
            "import_roots": ["imported package roots supplied by those dependencies"],
            "setup_instructions": "Human-readable setup notes; never a host shell script.",
        },
        "preparation_findings": findings(view, candidate_ref=view.candidate.ref.as_record()),
        "boundary": "The Target Workflow environment is separate from the coding agent's workspace and OpenChia's own environment.",
    }}


def _design(session, view, call):
    assignment = call.assignment
    owner = assignment.body["parent_assignment_ref"] if assignment.body["role"] == "implementer" else assignment.ref.as_record()
    plans = [row.record for row in view.entries("plan") if row.record.body["assignment_ref"] == owner]
    if not plans:
        return {"design": None}
    body = plans[-1].as_record()["body"]
    catalog = requirement_catalog(view)
    return {"design": {
        "approach": body["approach_key"],
        "requirement_mapping": {requirement_address(catalog[key]): text for key, text in body["requirement_mapping"].items()},
        "intended_change_scope": body["intended_change_scope"],
        "dependency_effects": body["dependency_effects"],
    }}


def _measure_design(session, view, call):
    from .measure_design import context
    from .measure_needs import catalog as needs
    from .measure_controls import control_context
    from .authored_checks import control_context as authored_control_context

    assignment = call.assignment
    proposals = [row.record for row in view.entries("measure_proposal")
                 if row.record.body["assignment_ref"] == assignment.ref.as_record()]
    current = proposals[-1:]  # resume_instrument selects this current proposal.
    catalog = requirement_catalog(view)
    controls = control_context(view, (item.ref for item in current))
    return {
        **context(view, assignment, session.policy),
        "measure_needs": [{
            "kind": need["kind"], "purpose": need["purpose"],
            "requirements": [requirement_address(catalog[key]) for key in need["requirement_keys"]],
        } for need in needs(view, assignment, session.policy)],
        "current_instrument": None if not current else {
            "purpose": current[0].body["purpose"],
            "requirements": [requirement_address(catalog[key]) for key in current[0].body["requirement_keys"]],
            "oracle_kind": current[0].body["oracle_kind"],
        },
        "measure_controls": [{
            key: row[key] for key in ("status", "gap", "outcome", "error")
        } for row in controls],
        "checking_program_controls": authored_control_context(view, current),
    }


def _grounding(session, view, call):
    from .grounding import grounding_context
    from .instrument_return import return_context

    return {
        **grounding_context(view, call.assignment, session.policy),
        "instrument_returns": return_context(view, call.assignment),
    }


def _investigation(session, view, call):
    from .investigation import needs

    catalog = requirement_catalog(view)
    return {
        "investigation_needs": [{
            "requirement": requirement_address(catalog[need["requirement_key"]]),
            "observation_path": view.read(Ref.from_record(need["check_ref"]), "check").body["observation_path"],
            "outcomes": _thaw_json(need["outcomes"]),
            **{name: view.data(Ref.from_record(need[name + "_ref"]))
               for name in ("decision", "target", "applicability")},
            "limitations": [view.data(Ref.from_record(ref)) for ref in need["limitation_refs"]],
        } for item in needs(view, session.policy, call.assignment) for need in (item["need"],)],
    }


_COMPONENTS = {
    "measurements": _measurements,
    "coordination": _coordination, "materialization": _materialization,
    "source": _source, "design": _design, "measure_design": _measure_design,
    "grounding": _grounding, "investigation": _investigation,
    "prerequisites": _prerequisites,
    "environment": _environment,
}


def reasoning_inputs(inputs):
    """Render a review's repeated fixture files once, retaining every exact control.

    The immutable working context and executable definition keep full file maps.
    Only the reasoning view uses inline source references; native coding still
    receives the complete files in its workspace.
    """
    checking = inputs.get("check_design")
    if not checking or not checking["review_assigned"]:
        return inputs
    result = _thaw_json(inputs)
    checking = result["check_design"]
    design = checking["current_design"]
    checking["execution_bindings"] = [
        item for item in checking["execution_bindings"]
        if item["purpose"] == design["purpose"]
    ]
    if design["program"] is None:
        return result
    files = [
        control["fixture"]["files"]
        for case in design["cases"]
        for polarity in ("positive_controls", "negative_controls")
        for control in case[polarity]
    ]
    counts = Counter(source for mapping in files for source in mapping.values())
    shared, labels = {}, {}
    for mapping in files:
        for path, source in mapping.items():
            if counts[source] < 2:
                continue
            if source not in labels:
                label, suffix = path, 2
                while label in shared:
                    label = f"{path} ({suffix})"
                    suffix += 1
                labels[source] = label
                shared[label] = source
            mapping[path] = {"shared_source": labels[source]}
    if shared:
        checking["shared_fixture_sources"] = shared
        checking["fixture_source_format"] = (
            "Each fixture.files entry is exact source text or {shared_source: NAME}. "
            "Resolve NAME in shared_fixture_sources to obtain that file's complete "
            "source at its original path. Shared text appears once in this review "
            "view; every control, input, materialization and rationale remains separate. "
            "The stored definition and executed fixtures retain the full file contents."
        )
    return result


def model_inputs(session, view, call):
    assignment = call.assignment
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    role = assignment.body["role"]
    catalog = requirement_catalog(view)
    contribution = set(assignment.body["contribution_requirement_keys"])
    preservation = [
        key for key in assignment.body["preservation_requirement_keys"]
        if key not in contribution
    ]
    need = goal.get("measure_request")
    result = {
        "assignment": {
            "role": role, "goal": goal["goal"],
            "requirements": assigned_addresses(session, assignment),
            "preservation_requirements": [
                requirement_address(catalog[key]) for key in preservation
            ],
            "writable_paths": list(assignment.body["writable_paths"]),
            "protected_paths": list(assignment.body["protected_paths"]),
            "allowed_children": list(assignment.body["allowed_child_bindings"]),
            "measure_request": None if need is None else {
                "purpose": need["purpose"],
                "requirements": [requirement_address(catalog[key]) for key in need["requirement_keys"]],
            },
            "return_contract": assigned_return_contract(view, assignment),
        },
        **{
            name: {
                requirement_address(catalog[key]): {
                    "evidence_scope": catalog[key]["evidence_scope"],
                    "requirement": _thaw_json(catalog[key]["approved_value"])
                    if "approved_value" in catalog[key] else catalog[key]["description"],
                    "mandatory": catalog[key]["mandatory"],
                } for key in keys
            }
            for name, keys in (
                ("requirements", assignment.body["contribution_requirement_keys"]),
                ("preservation_requirements", preservation),
            )
        },
    }
    for component in MODEL_INPUT_COMPONENTS[role]:
        delivered = _COMPONENTS[component](session, view, call)
        for key, value in delivered.items():
            if key == "source_kinds":
                result.setdefault(key, {}).update(value)
            else:
                result[key] = value
    if call.feedback_ref is not None:
        result["last_feedback"] = _feedback(session, view, call)
    return result


def _feedback(session, view, call):
    """Deliver the last operation's actionable result, not its audit envelope."""
    value = view.data(call.feedback_ref)
    if "source_workflow_ref" in value and "result" in value:
        from .candidate_environment import project_finding

        return {"task": "environment_preparation", **project_finding(value, call.feedback_ref)}
    if "proposal_ref" in value and "reason" in value:
        from .evaluation_experiments import feedback

        rejected = feedback(session, call.feedback_ref)["rejected_proposal"]
        return {
            "task": value["task"], "reason": value["reason"],
            "rejected_output": rejected["raw_response"],
        }
    if "execution_status" in value:
        from .evaluation_experiments import feedback

        recorded = feedback(session, call.feedback_ref)
        return {
            "task": "experiment", "execution_status": value["execution_status"],
            "observed_checks": len(value.get("observed_check_keys", ())),
            "control_observed": value.get("observed_control_ref") is not None,
            "environment_findings": value["environment_findings"],
            **_experiment_findings(view, recorded),
        }
    if "plan" in value:
        plan = value["plan"]
        return {
            "task": "experiment", "resolved": plan["resolved"],
            "gaps": plan["gaps"],
        }
    raise ValueError("refinement feedback has no declared model-facing projection")


def _experiment_findings(view, recorded):
    """Keep the chosen experiment's diagnostics visible without expanding audit logs."""
    spec = recorded.get("spec")
    if spec is None:
        return {}
    result = {
        "question": spec["question"], "scope": spec["scope"], "mode": spec["mode"],
        "candidate_matches_current": recorded["candidate_ref"] == view.candidate.ref.as_record(),
        "interpretation": "Findings apply to this experiment's scope and inputs. Campaign acceptance and credit are recorded separately.",
    }
    measurement = recorded["measurement"]
    if measurement is not None:
        catalog = requirement_catalog(view)
        outcomes = []
        for row in measurement["outcomes"]:
            observed = row["observed"]
            if isinstance(observed, dict) and observed.get("schema_id") == "openchia.measurement.observation-reference":
                observed = {
                    "source": observed["source"], "path": observed["path"],
                    "coverage": observed["coverage"], "detail": "Exact evidence retained in this experiment's measurement report.",
                }
            outcomes.append({
                "requirement": requirement_address(catalog[row["requirement_key"]])
                if row["requirement_key"] in catalog else None,
                **{key: row[key] for key in (
                    "status", "predicted", "falsifying", "criterion_expected", "reason", "limitations",
                )},
                "observed": observed,
            })
        result.update(outcomes=outcomes, limitations=measurement["limitations"])
    numerical = recorded["numerical"]
    if numerical is not None:
        result.update(
            controller_comparison=numerical["controller_comparison"],
            unobserved_local_ids=numerical["unobserved_local_ids"],
            limitations=numerical["limitations"],
            invocations=[{
                "local_id": row["local_id"], "episode_path": row["episode_path"],
                "units_compared": len(row["units"]),
                "matching_units": sum(unit["matches"] for unit in row["units"]),
                "differences": [{key: unit[key] for key in ("unit_id", "recorded", "recomputed")}
                                for unit in row["units"] if not unit["matches"]],
            } for row in numerical["invocations"]],
        )
    return result
