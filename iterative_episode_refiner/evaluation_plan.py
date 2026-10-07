"""Resolve an assignment's actual measurement prerequisites before execution.

The common evaluation service and campaign admission use this same projection.
Unavailable instruments are parent decisions, not worker errors or invented
observations. A coverage gap need not prevent running the available checks.
"""

from agent.duet_contracts import canonical_json

from .checking import checker_definition
from .evaluation_inputs import (
    candidate_payload_contract,
    native_launch,
    native_template,
)
from .measures import authorized_check_refs, bindings_for_check, evaluation_bindings
from .records import Ref


def resolve_evaluations(view, policy, assignment, purpose, *, selected=None):
    measure = assignment.body[
        "acceptance_measure_ref"
        if assignment.body["role"] in {"parts", "designer"}
        else "local_measure_ref"
    ]
    scope = set(assignment.body["scope_requirement_keys"])
    checks = tuple(
        check
        for reference in authorized_check_refs(view, policy, assignment)
        for check in (view.read(reference, "check"),)
        if check.body["measure_ref"] == measure
        and check.body["purpose"] == purpose
        and check.body["requirement_key"] in scope
        and (selected is None or check.artifact_id.value in selected)
    )
    keys = {check.artifact_id.value for check in checks}
    if selected is not None and keys != set(selected):
        raise ValueError(
            "selected evaluation checks are outside their exact measure or scope"
        )
    bindings = [
        binding
        for binding in evaluation_bindings(view, policy, assignment)
        if binding["measure_ref"] == measure and binding["purpose"] == purpose
    ]
    groups = {}
    for check in checks:
        choices = bindings_for_check(bindings, check)
        binding = choices[0] if len(choices) == 1 else None
        key = (
            canonical_json(binding)
            if binding is not None
            else ("ambiguous" if choices else "missing")
        )
        group = groups.setdefault(key, {"checks": [], "choices": choices})
        group["checks"].append(check)
    if not groups:
        groups["empty"] = {
            "checks": [],
            "choices": tuple({canonical_json(row): row for row in bindings}.values()),
        }
    return tuple(
        _group_plan(
            view,
            assignment,
            measure,
            purpose,
            tuple(group["checks"]),
            checks,
            group["choices"],
            selected,
        )
        for _, group in sorted(groups.items())
    )


def _group_plan(
    view, assignment, measure, purpose, checks, all_checks, choices, selected
):
    binding = choices[0] if len(choices) == 1 else None
    keys = {check.artifact_id.value for check in all_checks}
    gaps = []

    def gap(kind, detail, *, requirements=(), check_keys=()):
        gaps.append({
            "kind": kind,
            "detail": detail,
            "requirement_keys": sorted(requirements),
            "check_keys": sorted(check_keys),
        })

    installed = {row.record.ref for row in view.entries("check")}
    uninstalled = {
        check.artifact_id.value for check in checks if check.ref not in installed
    }
    if uninstalled:
        gap(
            "checks_unavailable",
            "These frozen checks have not been installed for observation.",
            check_keys=uninstalled,
        )
    covered = {
        check.body["requirement_key"] for check in all_checks if check.body["mandatory"]
    }
    # Investigation units deliberately select one discriminating observation;
    # not selecting every named question at once is not missing infrastructure.
    missing = set(assignment.body["contribution_requirement_keys"]) - covered
    if missing and selected is None:
        gap(
            "coverage_missing",
            "The frozen measure lacks mandatory checks for these requirements.",
            requirements=missing,
        )
    required_guards = {guard for check in checks for guard in check.body["guard_keys"]}
    missing_guards = required_guards - keys
    if missing_guards:
        gap(
            "guards_unavailable",
            "The measure cannot run all declared preservation guards.",
            check_keys=missing_guards,
        )
    incompatible = {
        check.artifact_id.value
        for check in checks
        if check.body["environment_ref"] != view.contract.body["environment_ref"]
    }
    if incompatible:
        gap(
            "environment_mismatch",
            "Checks require a different environment from the frozen campaign.",
            check_keys=incompatible,
        )
    if binding is None:
        gap(
            "instrument_missing" if not choices else "instrument_ambiguous",
            "Each check needs exactly one admitted instrument/input binding.",
        )
    else:
        instrument = view.data(Ref.from_record(binding["harness_ref"]))
        view.data(Ref.from_record(binding["capability_ref"]))
        if instrument.get("execution_kind") == "checking_program":
            from .authored_checks import instrument as checking_program

            try:
                checking_program(view, binding)
                if any(check.body["evidence_kind"] != "checking_program" for check in checks):
                    raise ValueError("checking program cannot substitute for another evidence kind")
            except (ValueError, KeyError, TypeError) as exc:
                gap("launch_input_invalid", str(exc))
        elif instrument.get("execution_kind") not in {
            "target_workflow",
            "instrument_build",
            "reference_workflow",
        } or (
            instrument.get("execution_kind") == "target_workflow"
            and instrument.get("target_workflow_ref")
            != view.contract.body["target_workflow_ref"]
        ):
            gap(
                "instrument_route_unavailable",
                "This admitted instrument needs an execution/input route not supported by native Target Workflow evaluation.",
            )
        else:
            try:
                if instrument.get("execution_kind") in {
                    "instrument_build",
                    "reference_workflow",
                } and any(
                    check.body["evidence_kind"] != "execution" for check in checks
                ):
                    raise ValueError(
                        "instrument builds and reference sources require declared execution checks"
                    )
                if instrument.get(
                    "execution_kind"
                ) == "reference_workflow" and assignment.body["role"] not in {
                    "question",
                    "support",
                }:
                    raise ValueError(
                        "reference acquisition cannot substitute for target repair or acceptance"
                    )
                checker_definition(view, binding)
                if any(check.body["evidence_kind"] == "execution" for check in checks):
                    native_launch(
                        view, binding, candidate_payload_contract(view, binding)
                    )
                else:
                    native_template(view, binding)
            except (ValueError, KeyError, TypeError) as exc:
                gap("launch_input_invalid", str(exc))
    executable = bool(checks) and not any(
        item["kind"] != "coverage_missing" for item in gaps
    )
    return {
        "binding": binding
        or {
            "measure_ref": measure,
            "purpose": purpose,
            "harness_ref": None,
            "capability_ref": None,
            "input_refs": [],
        },
        "checks": checks,
        "selection_check_keys": sorted(selected) if selected is not None else None,
        "availability": {"executable": executable, "gaps": gaps},
    }


def evaluation_availability(plans):
    gaps = {
        canonical_json(gap): gap
        for plan in plans
        for gap in plan["availability"]["gaps"]
    }
    return {
        "executable": any(plan["availability"]["executable"] for plan in plans),
        "gaps": [value for _, value in sorted(gaps.items())],
    }


def unavailable_request(view, attempt):
    """An exact unsatisfied evaluation prerequisite from this invocation/unit."""
    return next(
        iter(
            unavailable_requests(view, attempt.invocation_id, attempt.logical_unit_id)
        ),
        None,
    )


def unavailable_requests(view, invocation_id, logical_unit_id):
    """Retain both preflight and post-target gaps across every evaluated case."""
    seen = set()
    pending = []
    runs = {row.key: row.record for row in view.entries("evaluation_run")}
    for row in reversed(view.entries("evaluation")):
        request = row.record
        if (
            request.invocation_id != invocation_id
            or request.logical_unit_id != logical_unit_id
        ):
            continue
        key = canonical_json({
            field: request.body[field]
            for field in (
                "measure_ref",
                "purpose",
                "harness_ref",
                "capability_ref",
                "input_refs",
                "check_keys",
            )
        })
        if key in seen:
            continue
        seen.add(key)
        if request.body.get("availability", {}).get("gaps"):
            pending.append(request)
        execution = runs.get(request.artifact_id.value)
        if execution is not None and "checking_gap" in execution.body:
            pending.append(execution)
    return tuple(pending)
