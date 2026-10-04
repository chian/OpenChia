"""First-time check design and review within the existing campaign ledger.

These are proposals about how to test, not observations that the Target Workflow
passed. Separate review preserves judgment provenance; executable controls and
the ordinary measure admission boundary still decide whether a check is usable.
"""

from collections.abc import Mapping

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact, names
from function_library.refinement_checks import resolve_predicate

from .records import Ref


REVIEW_CRITERIA = (
    "original_requirement_preserved",
    "observation_tests_requirement",
    "expected_result_justified",
    "controls_have_justified_polarities",
    "limitations_are_explicit",
)
DESIGN_FIELDS = {
    "purpose",
    "predicate",
    "cases",
    "input_domain",
    "observation_schema",
    "execution_binding",
    "limitations",
}
CASE_FIELDS = {
    "requirement_key",
    "rationale",
    "expected",
    "observation_path",
    "positive_controls",
    "negative_controls",
}


def policy(grant):
    value = grant.get("reviewed_designs") if grant else None
    if value is not None and value != {"version": 1}:
        raise ValueError("unsupported reviewed check-design policy")
    return value


def validate_design(value):
    exact(value, DESIGN_FIELDS, "check design")
    if value["purpose"] not in {"local", "acceptance", "composition", "adequacy"}:
        raise ValueError("check design has an unknown purpose")
    if value["predicate"]["interface"] != "refinement.predicate":
        raise ValueError("check design must select a registered observation predicate")
    resolve_predicate(value["predicate"])
    for field in ("input_domain", "observation_schema"):
        if not isinstance(value[field], Mapping) or not value[field]:
            raise ValueError(f"check design needs an explicit {field} record")
    if not isinstance(value["cases"], (list, tuple)) or not value["cases"]:
        raise ValueError("check design needs explicit cases")
    names(value["limitations"], "check limitations", nonempty=True)
    exact(
        value["execution_binding"],
        {"harness_ref", "capability_ref", "input_refs"},
        "check execution binding",
    )
    binding = value["execution_binding"]
    Ref.from_record(binding["harness_ref"])
    Ref.from_record(binding["capability_ref"])
    if not isinstance(binding["input_refs"], (list, tuple)):
        raise ValueError("check inputs must be exact reference arrays")
    for reference in binding["input_refs"]:
        Ref.from_record(reference)
    for case in value["cases"]:
        exact(case, CASE_FIELDS, "designed check case")
        names(
            (case["requirement_key"], case["rationale"]),
            "requirement and rationale",
            nonempty=True,
        )
        from episode_runtime.testing_harness.observations import validate_observation_path

        validate_observation_path(case["observation_path"])
        if value["predicate"]["function_id"] == "record_conditions_v1":
            from function_library.record_conditions import validate_condition

            validate_condition(case["expected"])
        seen = set()
        for field in ("positive_controls", "negative_controls"):
            if not isinstance(case[field], (list, tuple)) or not case[field]:
                raise ValueError("check design needs both control polarities")
            for control in case[field]:
                exact(control, {"observed", "rationale"}, "proposed check control")
                names((control["rationale"],), "control rationale", nonempty=True)
                key = canonical_json(control["observed"])
                if key in seen:
                    raise ValueError(
                        "check controls cannot repeat or contradict each other"
                    )
                seen.add(key)


def validate_review(value):
    exact(
        value,
        {"definition_ref", "criteria", "counterexamples", "limitations"},
        "check review",
    )
    Ref.from_record(value["definition_ref"])
    exact(value["criteria"], set(REVIEW_CRITERIA), "check review criteria")
    for finding in value["criteria"].values():
        exact(finding, {"satisfied", "reason"}, "check review finding")
        if type(finding["satisfied"]) is not bool:
            raise ValueError("review finding must have an explicit boolean judgment")
        names((finding["reason"],), "review reasoning", nonempty=True)
    names(value["counterexamples"], "review counterexamples")
    names(value["limitations"], "review limitations", nonempty=True)


def _grant(view):
    from .measure_needs import admission_policy

    frozen = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    grant = admission_policy(frozen)
    if not policy(grant):
        raise ValueError("campaign does not authorize reviewed check design")
    return frozen, grant


def _definition(view, reference):
    reference = Ref.from_record(reference)
    entry = view.entry("measure_definition", reference.artifact_id.value)
    if entry.record.ref != reference or entry.status != "proposed":
        raise ValueError("check definition is not an indexed immutable proposal")
    return entry.record


def assigned_definition(view, assignment):
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    reference = goal.get("measure_review_ref")
    if reference is None:
        return None
    _, grant = _grant(view)
    definition = _definition(view, reference)
    if (
        assignment.body["role"] != "question"
        or assignment.body["parent_assignment_ref"] != definition.body["assignment_ref"]
        or assignment.body["local_measure_ref"] != grant["adequacy_measure_ref"]
        or set(assignment.body["contribution_requirement_keys"])
        != {case["requirement_key"] for case in definition.body["design"]["cases"]}
        or reference not in assignment.body["input_refs"]
    ):
        raise ValueError(
            "review must be assigned to a separate child of the check designer"
        )
    return definition


def propose(view, attempt):
    from .state_machine import actor, derived, index

    assignment = actor(view, attempt)
    frozen, grant = _grant(view)
    payload = attempt.body["payload"]
    if "check_design" in payload:
        exact(payload, {"check_design"}, "check design proposal")
        design = payload["check_design"]
        validate_design(design)
        if assignment.body["role"] != "measure":
            raise ValueError(
                "only the assigned Measure Episode may design its requested check"
            )
        if assignment.body["local_measure_ref"] != grant["adequacy_measure_ref"]:
            raise ValueError(
                "the parent assigned the wrong local measure: check design requires "
                "measure_admission_policy.adequacy_measure_ref. Revising a check "
                "proposal cannot repair this frozen assignment"
            )
        goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
        need = goal["measure_request"]
        keys = {case["requirement_key"] for case in design["cases"]}
        if design["purpose"] != need["purpose"] or keys != set(
            need["requirement_keys"]
        ):
            raise ValueError(
                "check design must preserve exactly the parent's requested judgment"
            )
        catalog = view.data(
            Ref.from_record(view.contract.body["requirement_catalog_ref"])
        )
        if not keys <= {row["requirement_key"] for row in catalog["requirements"]}:
            raise ValueError("check design cites a nonexistent original requirement")
        binding = design["execution_binding"]
        if not any(
            item["purpose"] == design["purpose"]
            and all(
                canonical_json(item[key]) == canonical_json(value)
                for key, value in binding.items()
            )
            for item in frozen["evaluation_bindings"]
        ):
            raise ValueError("check design cannot invent execution authority")
        record = derived(
            view,
            attempt,
            "measure_definition",
            {
                "assignment_ref": assignment.ref.as_record(),
                "owner_assignment_ref": assignment.body["parent_assignment_ref"],
                "requirement_catalog_ref": view.contract.body[
                    "requirement_catalog_ref"
                ],
                "design": design,
            },
        )
        collection, status = "measure_definition", "proposed"
    else:
        exact(payload, {"check_review"}, "check review proposal")
        review = payload["check_review"]
        validate_review(review)
        definition = assigned_definition(view, assignment)
        if definition is None or review["definition_ref"] != definition.ref.as_record():
            raise ValueError(
                "review does not address the exact assigned check definition"
            )
        if attempt.invocation_id == definition.invocation_id:
            raise ValueError("a check designer cannot review its own definition")
        record = derived(
            view,
            attempt,
            "measure_review",
            {
                "assignment_ref": assignment.ref.as_record(),
                **review,
            },
        )
        collection, status = "measure_review", "reviewed"
    return [record], [index(collection, record.artifact_id.value, record, status)]


def reviewed(view, definition_ref, assignment):
    """Resolve a returned review, never treating a stored model claim as approval."""
    _grant(view)
    definition = _definition(view, definition_ref)
    if definition.body["assignment_ref"] != assignment.ref.as_record():
        raise ValueError("reviewed check belongs to another Measure assignment")
    reviews = []
    for entry in view.entries("measure_review"):
        record = entry.record
        if record.body["definition_ref"] != definition.ref.as_record():
            continue
        reviewer = view.entry("invocation", record.invocation_id.value)
        if (
            reviewer.status != "returned"
            or assigned_definition(view, reviewer.record).ref != definition.ref
        ):
            raise ValueError("check review has not returned through its assigned child")
        # Independently re-derive the review from its committed attempt.
        attempt = view.read(record.predecessor_refs[0], "attempt")
        if attempt.body["action"] != "propose_measure" or canonical_json(
            attempt.body["payload"].get("check_review")
        ) != canonical_json({
            key: record.body[key]
            for key in ("definition_ref", "criteria", "counterexamples", "limitations")
        }):
            raise ValueError("review differs from its recorded proposal")
        reviews.append(record)
    if not reviews:
        raise ValueError("check definition needs a separately returned review")
    # A contrary review cannot be cherry-picked away. Revise the definition.
    if any(
        record.body["counterexamples"]
        or not all(item["satisfied"] for item in record.body["criteria"].values())
        for record in reviews
    ):
        raise ValueError("check review requires revision before admission")
    return definition, tuple(reviews)


def unit_review(view, attempt):
    return next(
        (
            row.record
            for row in view.entries("measure_review")
            if row.record.invocation_id == attempt.invocation_id
            and row.record.logical_unit_id == attempt.logical_unit_id
        ),
        None,
    )




def context(view, assignment, frozen):
    """The current instrument under construction, not the design/review history."""
    from function_library.refinement_checks import refinement_check_library
    from function_library.models import _thaw_json
    from episode_runtime.testing_harness.observations import observation_catalog
    from .report_contract import requirement_address, requirement_catalog

    grant = frozen.get("measure_admission")
    if not policy(grant):
        return {}
    selected = assigned_definition(view, assignment)
    definitions = [
        row.record for row in view.entries("measure_definition")
        if row.record.body["assignment_ref"] == assignment.ref.as_record()
    ]
    current = selected or (definitions[-1] if definitions else None)
    design = None
    if current is not None:
        design = _thaw_json(current.body["design"])
        catalog = requirement_catalog(view)
        design["cases"] = [{
            **{key: value for key, value in case.items() if key != "requirement_key"},
            "requirement": requirement_address(catalog[case["requirement_key"]]),
        } for case in design["cases"]]
    return {
        "check_design": {
            "current_design": design,
            "review_assigned": selected is not None,
            "review_criteria": list(REVIEW_CRITERIA),
            "available_predicates": [
                function.as_record() for function in refinement_check_library.functions()
            ],
            "available_observations": observation_catalog(),
            "execution_bindings": [
                item for item in frozen["evaluation_bindings"]
                if item["purpose"] in {"local", "acceptance", "composition", "adequacy"}
            ],
            "authority": (
                "Propose a requirement-grounded instrument and its controls. A separately assigned "
                "Question reviews it; executable controls establish its measured adequacy. "
                "Use the contracted child return to revise the current design or submit it with "
                "submit_reviewed_design. Prior reviews describe limitations, not target success."
            ),
        }
    }
