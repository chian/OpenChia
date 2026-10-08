"""Host admission for campaign stage operations.

No public operation accepts a state delta or credit amount. Parent proposals are
checked against their frozen scope; all resulting indexes are derived here.
"""

from __future__ import annotations

from agent.duet_contracts import content_id
from agent.duet_store import DuetConflictError
from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact
from function_library.refinement_contract import CHILDREN as ROLES
from function_library.refinement_contract import (
    IMPLEMENTATION_ROLES,
    PARTS_ROLES,
    ROLE_SPECIALIZATION,
)

from .campaign_store import CampaignView
from .evidence import ResolvedEvidence
from .records import Ref, RefinementRecord, logical_path


def index(collection, key, record, status="active"):
    return {
        "kind": "index",
        "collection": collection,
        "key": key,
        "record_id": record.artifact_id.value,
        "status": status,
    }


def derived(view, attempt, kind, body, *, evidence=None):
    return RefinementRecord(
        kind,
        view.campaign_id,
        body,
        view.contract.producer_ref,
        attempt.evidence_refs if evidence is None else evidence,
        (attempt.ref,),
        attempt.invocation_id,
        attempt.logical_unit_id,
    )


def proposed(view, attempt, key, kind):
    record = RefinementRecord.from_record(attempt.body["payload"][key])
    if record.kind != kind or record.campaign_id != view.campaign_id:
        raise ValueError("proposal kind or campaign does not match")
    return record


def actor(view, attempt):
    from .coordination import pending_decisions

    invocation = view.entry("invocation", attempt.body["invocation_id"])
    returning = attempt.body["action"] == "return_child" and invocation.status in {
        "attained",
        "yield_exhausted_unresolved",
        "needs_parent_decision",
    }
    closing_decision = (
        attempt.body["action"] == "close_unit"
        and invocation.status == "needs_parent_decision"
    )
    if invocation.status != "active" and not returning and not closing_decision:
        raise ValueError("only the currently active invocation may select or edit")
    if attempt.body["action"] not in invocation.record.body["allowed_action_classes"]:
        raise ValueError("action is outside the frozen assignment")
    if pending_decisions(view, invocation.key) and attempt.body["action"] not in {
        "observe",
        "observe_materialization",
        "observe_checker",
        "observe_measure_control",
        "close_unit",
        "return_child",
    }:
        raise ValueError(
            "ordinary repairs are suspended pending the coordinating Episode's decision"
        )
    return invocation.record


def judgment_lineage(body):
    # Renaming/restarting an assignment is not a new judgment. The exact measure
    # carries original requirement identities and the applicability cohort.
    return content_id(
        "judgment", {"role": body["role"], "measure": body["local_measure_ref"]}
    ).value


def implementation_scope(role, source_paths, materialization_targets):
    """Capabilities belong to the specialist, independent of its model prompt."""
    specialization = ROLE_SPECIALIZATION[role]
    if specialization == "implementer" and materialization_targets:
        raise ValueError("Code Implementer has source authority only")
    if specialization == "materialization_implementer" and source_paths:
        raise ValueError("MaterializationImplementer has plan authority only")
    if specialization not in {"designer", "materialization_implementer"} and materialization_targets:
        raise ValueError("this role cannot hold materialization edit authority")
    if specialization not in {"designer", "implementer"} and source_paths:
        raise ValueError("this role cannot hold Target Workflow source edit authority")


def design_plan_for(view, assignment):
    """Resolve the latest general approach through actual Designer ancestry."""
    from .coordination import ancestors

    designer = next(
        (item for item in ancestors(view, assignment) if item.body["role"] == "designer"),
        None,
    )
    if designer is None:
        return None
    plans = [
        entry.record for entry in view.entries("plan")
        if entry.record.body["assignment_ref"] == designer.ref.as_record()
    ]
    return plans[-1] if plans else None


def _install_assignment(view, attempt, resolved):
    payload = exact(
        attempt.body["payload"], {"assignment", "invocation_id"}, "assignment proposal"
    )
    assignment = proposed(view, attempt, "assignment", "assignment")
    return admit_assignment(
        view, attempt, resolved, assignment, payload["invocation_id"]
    )


def admit_assignment(view, attempt, resolved, assignment, invocation_id):
    from .investigation import require_assignment
    from .succession import require_measures, validate_replacements
    from .measure_needs import validate_assignment_prerequisites
    from .report_contract import assigned_return_contract

    body = assignment.body
    implementation_scope(body["role"], body["writable_paths"], body["materialization_targets"])
    if not set(body["materialization_targets"]) <= set(resolved.references["policy"]["materialization_edit_targets"]):
        raise ValueError("assignment names an unapproved materialization target")
    assigned_return_contract(view, assignment)
    require_assignment(view, resolved.references["policy"], assignment)
    invocation_id = OpaqueId(invocation_id).value
    if body["judgment_lineage"] != judgment_lineage(body):
        raise ValueError("assignment cannot reset its semantic judgment lineage")
    if any(row.key == invocation_id for row in view.entries("invocation")):
        raise DuetConflictError("invocation identity already exists")
    view.read(Ref.from_record(body["baseline_candidate_ref"]), "candidate")
    root = body["parent_assignment_ref"] is None
    replacements = ()
    if root:
        if (
            view.entries("assignment")
            or body["role"] != "designer"
            or body["coordinating_invocation_id"] != invocation_id
        ):
            raise ValueError("campaign has exactly one root Designer assignment")
        if assignment.ref.as_record() != resolved.references["policy"].get(
            "root_assignment_ref"
        ):
            raise ValueError("root assignment is not the frozen host entry point")
        if body["supersedes_assignment_refs"]:
            raise ValueError("a new root contract requires the approval boundary")
    else:
        parent = actor(view, attempt)
        validate_assignment_prerequisites(view, parent, assignment)
        if (
            Ref.from_record(body["parent_assignment_ref"]) != parent.ref
            or body["role"] not in ROLES[parent.body["role"]]
        ):
            raise ValueError(
                "parent cannot create this role or bypass the approved nesting"
            )
        if body["role"] not in parent.body["allowed_child_bindings"]:
            raise ValueError("child binding was not approved")
        for field in ("scope_requirement_keys", "owned_slice_keys", "writable_paths", "materialization_targets"):
            if not set(body[field]).issubset(parent.body[field]):
                raise ValueError(f"child expands {field}")
        if not set(parent.body["protected_paths"]).issubset(body["protected_paths"]):
            raise ValueError("child removes a protected path")
        if body["authority_ref"] != parent.body["authority_ref"]:
            raise ValueError("new authority requires explicit parent admission")
        owner = view.entry("invocation", body["coordinating_invocation_id"])
        if owner.key != attempt.body["invocation_id"] or owner.record.ref != parent.ref:
            raise ValueError("assignment must retain its actual coordinating parent")
        if body["role"] in PARTS_ROLES.values():
            if ROLE_SPECIALIZATION[body["role"]] != ROLE_SPECIALIZATION[parent.body["role"]]:
                raise ValueError("Parts must retain their parent's specialization")
            dimensions = ("contribution_requirement_keys", "writable_paths", "materialization_targets")
            if any(not set(body[field]) <= set(parent.body[field]) for field in dimensions):
                raise ValueError("Parts cannot expand their parent's assigned work")
            if not any(set(body[field]) < set(parent.body[field]) for field in dimensions):
                raise ValueError(
                    "Parts requires a smaller requirement or concrete target scope. "
                    "A single requirement may be divided by source paths or plan targets; "
                    "perform same-scope work directly with this Episode's own capabilities."
                )
        replacements = validate_replacements(
            view, attempt, parent, assignment, resolved.references["policy"]
        )
        require_measures(view, resolved.references["policy"], assignment)
    deltas = [
        index("assignment", assignment.artifact_id.value, assignment),
        index("invocation", invocation_id, assignment, "active" if root else "ready"),
    ]
    for prior, prior_invocation in replacements:
        deltas.append(index("invocation", prior_invocation, prior, "superseded"))
        deltas.append(index("assignment", prior.artifact_id.value, prior, "superseded"))
    return [assignment], deltas


def _enter_child(view, attempt, resolved):
    parent = actor(view, attempt)
    payload = exact(attempt.body["payload"], {"invocation_id"}, "child entry")
    child = view.entry("invocation", payload["invocation_id"])
    if (
        child.status != "ready"
        or Ref.from_record(child.record.body["parent_assignment_ref"]) != parent.ref
    ):
        raise ValueError("child is not a ready child of this invocation")
    return [], [
        index("invocation", child.key, child.record),
        index("invocation", attempt.body["invocation_id"], parent, "waiting"),
    ]


def _return_child(view, attempt, resolved):
    from .coordination import pending_decisions, return_owned_conflicts
    from .reports import parent_report

    child = actor(view, attempt)
    exact(attempt.body["payload"], set(), "child return")
    report = parent_report(view, OpaqueId(attempt.body["invocation_id"]))
    if report.body["termination"] == "continuing":
        raise ValueError("worker cannot stop an unresolved continuation")
    parent_ref = child.body["parent_assignment_ref"]
    parents = (
        [
            row
            for row in view.entries("invocation")
            if row.record.ref == Ref.from_record(parent_ref)
        ]
        if parent_ref
        else []
    )
    if len(parents) != 1 or parents[0].status != "waiting":
        raise ValueError("return has no suspended direct parent")
    parent = parents[0]
    conflicts, conflict_deltas = return_owned_conflicts(view, attempt, parent.record)
    awaiting_ancestor = any(
        item.body["scope_owner_invocation_id"] != parent.key for item in conflicts
    )
    parent_status = (
        "needs_parent_decision"
        if pending_decisions(view, parent.key) or awaiting_ancestor
        else "active"
    )
    return [report, *conflicts], [
        *conflict_deltas,
        index("invocation", attempt.body["invocation_id"], child, "returned"),
        index("invocation", parent.key, parent.record, parent_status),
        index("report", report.artifact_id.value, report),
    ]


def _admit_plan(view, attempt, resolved):
    from .measures import selected_measure_ref
    assignment = actor(view, attempt)
    if assignment.body["role"] != "designer":
        raise ValueError("only Designer proposes the general approach")
    exact(attempt.body["payload"], {"plan"}, "design plan submission")
    plan = proposed(view, attempt, "plan", "design_plan")
    body = plan.body
    if not set(body["intended_materialization_targets"]) <= set(assignment.body["materialization_targets"]):
        raise ValueError("plan expands the assignment's materialization targets")
    if (
        Ref.from_record(body["assignment_ref"]) != assignment.ref
        or body["open_need_refs"]
    ):
        raise ValueError(
            "plan must belong to this Designer and state a resolved general approach"
        )
    if not set(body["intended_change_scope"]).issubset(
        assignment.body["writable_paths"]
    ):
        raise ValueError("plan expands the assignment's editable scope")
    required = set(assignment.body["contribution_requirement_keys"])
    provided = set(body["requirement_mapping"])
    if provided != required:
        from .report_contract import requirement_address, requirement_catalog

        catalog = requirement_catalog(view)
        missing = sorted(requirement_address(catalog[key]) for key in required - provided)
        unexpected = sorted(requirement_address(catalog[key]) for key in provided - required)
        raise ValueError(
            "plan requirement_mapping must contain exactly the specification "
            "addresses in assignment.requirements: "
            f"missing={missing!r}, unexpected={unexpected!r}. "
            "Keep preservation-only requirements separate; do not add them "
            "to requirement_mapping."
        )
    if body["acceptance_measure_ref"] != selected_measure_ref(view, assignment, "acceptance_measure_ref"):
        raise ValueError("plan cannot redefine the parent's acceptance measure")
    if body["local_measure_ref"] != selected_measure_ref(view, assignment, "local_measure_ref"):
        raise ValueError("plan must use its owner's selected composite implementation measure")
    return [plan], [index("plan", plan.artifact_id.value, plan)]


def _apply_change(view, attempt, resolved):
    from .cycles import exact_revisit

    assignment = actor(view, attempt)
    role = assignment.body["role"]
    if role not in IMPLEMENTATION_ROLES:
        raise ValueError("only implementation specialists submit candidate changes")
    exact(attempt.body["payload"], {"change"}, "change submission")
    change = proposed(view, attempt, "change", "change")
    body = change.body
    specialization = ROLE_SPECIALIZATION[role]
    if specialization == "implementer" and body["implementation_detail_operations"]:
        raise ValueError("Code Implementer cannot submit materialization changes")
    if specialization == "materialization_implementer" and body["file_operations"]:
        raise ValueError("MaterializationImplementer cannot submit source changes")
    if any(item["requirement_key"] not in assignment.body["contribution_requirement_keys"]
           for item in body["findings"]):
        raise ValueError("implementation findings must concern assigned requirements")
    if Ref.from_record(body["assignment_ref"]) != assignment.ref:
        raise ValueError("change belongs to another assignment")
    if Ref.from_record(body["expected_head_ref"]) != view.candidate.ref:
        raise DuetConflictError("edit is based on a stale candidate")
    plan_ref = Ref.from_record(body["design_plan_ref"])
    plan = design_plan_for(view, assignment)
    if (
        plan is None
        or plan.ref != plan_ref
        or not set(assignment.body["contribution_requirement_keys"]) <= set(plan.body["requirement_mapping"])
    ):
        raise ValueError("change requires its owning Designer's latest admitted general approach")
    materialization = None
    detail_paths = set()
    if body["implementation_detail_operations"]:
        from .materialization_edits import target_source_paths

        edit = resolved.references["materialization_edit"]
        authorized_targets = set(
            resolved.references["policy"].get("materialization_edit_targets", ())
        )
        targets = set(edit["record"]["changed_targets"])
        if not (targets <= authorized_targets
                and targets <= set(assignment.body["materialization_targets"])
                and targets <= set(plan.body["intended_materialization_targets"])):
            raise ValueError(
                "materialization detail edit lacks exact frozen target authority"
            )
        detail_paths = set(edit["affected_source_paths"])
        if (
            not detail_paths.issubset(target_source_paths(view, assignment.body["materialization_targets"]))
            or not detail_paths.issubset(target_source_paths(view, plan.body["intended_materialization_targets"]))
            or detail_paths.intersection(assignment.body["protected_paths"])
        ):
            raise ValueError("plan edit escapes its assigned implementation scope")
        materialization = derived(view, attempt, "materialization", edit["record"])
    files = dict(view.candidate.body["files"])
    touched = set()
    for operation in body["file_operations"]:
        exact(
            operation,
            {"kind", "logical_path", "before_hash", "after_blob_hash"},
            "file operation",
        )
        path = logical_path(operation["logical_path"])
        if (
            path in touched
            or path not in assignment.body["writable_paths"]
            or path in assignment.body["protected_paths"]
            or path not in plan.body["intended_change_scope"]
        ):
            raise ValueError("edit repeats a path or escapes its approved scope")
        touched.add(path)
        before, after, kind = (
            operation["before_hash"],
            operation["after_blob_hash"],
            operation["kind"],
        )
        if files.get(path) != before or before == after:
            raise DuetConflictError("edit before hash is stale or change is empty")
        if kind == "add" and before is None and after is not None:
            files[path] = after
        elif kind == "replace" and before is not None and after is not None:
            files[path] = after
        elif kind == "remove" and before is not None and after is None:
            del files[path]
        else:
            raise ValueError("invalid file operation")
    if not touched and materialization is None:
        if not body["findings"]:
            raise ValueError("empty implementation submission")
        # Advisory findings are durable without fabricating a candidate revision,
        # progress fact, or an early-return decision for the Episode.
        return [change], []
    candidate = derived(
        view,
        attempt,
        "candidate",
        {
            **view.candidate.body,
            "files": files,
            "materialization_ref": materialization.ref.as_record()
            if materialization is not None
            else view.candidate.body["materialization_ref"],
            "parent_candidate_ref": view.candidate.ref.as_record(),
            "change_set_ref": change.ref.as_record(),
            "source_admission_ref": None,
        },
    )
    deltas = [
        {
            "kind": "head",
            "before": view.candidate.artifact_id.value,
            "after": candidate.artifact_id.value,
        }
    ]
    from .measurement import dependency_hashes

    for entry in view.entries("check_state"):
        check = view.entry("check", entry.key).record
        if dependency_hashes(check, view.candidate) != dependency_hashes(check, candidate):
            deltas.append(index("check_state", entry.key, entry.record, "stale"))
    conflicts = exact_revisit(view, attempt, candidate, materialization)
    deltas.extend(
        index("conflict", item.artifact_id.value, item, item.body["state"])
        for item in conflicts
    )
    return [
        change,
        *([materialization] if materialization is not None else []),
        candidate,
        *conflicts,
    ], deltas


def _install_check(view, attempt, resolved):
    assignment = actor(view, attempt)
    if assignment.body["role"] not in {"designer", "measure"}:
        raise ValueError("implementers and verifiers cannot change their checks")
    exact(attempt.body["payload"], {"check"}, "check submission")
    check = proposed(view, attempt, "check", "check")
    policy = resolved.references["policy"]
    if check.ref.as_record() not in policy["check_refs"]:
        raise ValueError("check has no admitted grounding/adequacy contract")
    if check.body["requirement_key"] not in assignment.body["scope_requirement_keys"]:
        raise ValueError("check is outside the assignment")
    key = check.artifact_id.value
    if any(entry.key == key for entry in view.entries("check")):
        return [], []
    return [check], [index("check", key, check)]


def admit_attempt(
    view: CampaignView, attempt: RefinementRecord, resolved: ResolvedEvidence
):
    from .context import select_action
    from .coordination import coordinate_conflict, resolve_conflict
    from .measurement import (
        admit_lesson,
        close_unit,
        observe,
        observe_materialization,
        request_evaluation,
    )
    from .measures import propose_measure
    from .measure_admission import admit_measure
    from .evaluation_admission import bind_run, record_source
    from .measure_controls import bind_control, observe_control
    from .authored_checks import observe as observe_checker
    from .research import admit_sources, admit_findings

    if (
        attempt.invocation_id is None
        or attempt.logical_unit_id is None
        or (
            attempt.invocation_id.value != attempt.body["invocation_id"]
            or attempt.logical_unit_id.value != attempt.body["logical_unit_id"]
        )
    ):
        raise ValueError("attempt provenance differs from its logical invocation/unit")
    if attempt.body["action"] != "return_child" and any(
        entry.record.invocation_id == attempt.invocation_id
        and entry.record.logical_unit_id == attempt.logical_unit_id
        for entry in view.entries("unit")
    ):
        raise DuetConflictError("logical unit has already closed")
    handlers = {
        "assign": _install_assignment,
        "enter_child": _enter_child,
        "return_child": _return_child,
        "admit_plan": _admit_plan,
        "apply_change": _apply_change,
        "install_check": _install_check,
        "propose_measure": propose_measure,
        "admit_measure": admit_measure,
        "bind_measure_control": bind_control,
        "observe_measure_control": observe_control,
        "request_evaluation": request_evaluation,
        "record_evaluation_source": record_source,
        "bind_evaluation_run": bind_run,
        "observe": observe,
        "observe_materialization": observe_materialization,
        "observe_checker": observe_checker,
        "admit_lesson": admit_lesson,
        "close_unit": close_unit,
        "select_action": select_action,
        "coordinate_conflict": coordinate_conflict,
        "resolve_conflict": resolve_conflict,
        "record_research_sources": admit_sources,
        "admit_research_findings": admit_findings,
    }
    try:
        handler = handlers[attempt.body["action"]]
    except KeyError as exc:
        raise ValueError("unregistered campaign operation") from exc
    return handler(view, attempt, resolved)
