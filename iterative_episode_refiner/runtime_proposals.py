"""Task-specific proposals admitted by the one refinement host session.

Models supply the behavioral choice, design, or source text. The host supplies
identity, authority, inherited constraints, candidate hashes and final records.
"""

from agent.duet_contracts import content_id
from function_library.epistemic_contract import exact, names
from function_library.models import _thaw_json
from function_library.refinement_contract import ROLES

from .records import Ref, logical_path
from .state_machine import judgment_lineage
from .report_contract import RETURN_SHAPE, requirement_address, validate_return_contract
from .assignment_choices import (
    assigned_addresses, conflict_choice, owned_slices, prerequisite_choice,
    replacements, requirement_keys,
)


_ASSIGNMENT_SHAPE = {
    "role": "one permitted child role",
    "goal": "precise behavioral contribution, not a file grouping",
    "requirements": [
        "Choose a nonempty set of specification addresses for this child's contribution "
        "from the parent's assignment.requirements. The inherited "
        "context retains the other requirements and their protections."
    ],
    "writable_paths": ["an exact path within the parent's editable scope"],
    "return_contract": RETURN_SHAPE,
    "measure_request": (
        "For role=measure, supply {purpose, requirements}. purpose is one literal category: "
        "local (implementation progress), acceptance (independent part acceptance), "
        "composition (whole-scope acceptance), or adequacy (instrument quality). "
        "requirements contains exactly the assignment's requirements. Explain the work in goal. "
        "For other roles supply null."
    ),
    "replace_previous": "true to replace the most recently returned child of this role for these requirements; otherwise false",
    "prerequisites": [{
        "kind": "Copy from a returned open_decisions entry marked assignment_prerequisite=true; use [] for new work.",
        "purpose": "Copy that entry's literal judgment category.",
        "requirements": [
            "copy that returned need's full specification addresses; its scope may be "
            "broader than this child's contribution"
        ],
    }],
}

_PREREQUISITE_ROLES = {
    "designer": ("support", "question", "measure"),
    "implementer": ("question",),
    "measure": ("question",),
}


def _prerequisite_shape(role):
    return {
        **_ASSIGNMENT_SHAPE,
        "role": "one of: " + ", ".join(_PREREQUISITE_ROLES[role]),
    }


_MEASURE_SHAPE = {
    "requirements": ["the parent's exact requested specification requirement addresses"],
    "purpose": "the parent's requested local, acceptance, composition or adequacy purpose",
    "oracle_kind": "registered_predicate or independent_execution",
    "oracle_ref": "exact committed reference to the proposed oracle",
    "input_domain_ref": "exact committed domain and applicability reference",
    "case_manifest": {
        "grounding_refs": [
            "compose exact independently authorized cases shown in measure_grounding"
        ]
    },
    "observation_schema_ref": "exact typed observations to collect",
    "decision_function_ref": "registered host predicate selection reference",
    "positive_control_refs": ["known satisfactory controls with original provenance"],
    "negative_control_refs": [
        "known violating and trivial-output controls with original provenance"
    ],
    "grounding_refs": [
        "requirement interpretation and independent expected-answer provenance"
    ],
    "independence_policy_ref": "independence requirement reference",
    "uncertainty_policy_ref": "limits of the conclusions the instrument can support",
    "limitation_refs": [],
    "instrument_return": "optional exact {spec_ref, report_ref, source_ref} from instrument_returns; omit for an already admitted checker",
    "acquired_grounding": "optional list of exact {acquisition_ref, report_ref, observation_ref} from acquired_grounding; the host adds those complete cases and controls",
}

_CHECK_DESIGN_SHAPE = {
    "purpose": "the parent's exact requested purpose",
    "predicate": "exact registered selection: library, function_id, definition_id, interface, arguments (no name)",
    "cases": [{
        "requirement": "original specification requirement address",
        "rationale": "derive expected behavior from the original requirement, not candidate output",
        "expected": "typed input to the selected predicate",
        "observation_path": "exact JSON pointer into the actual execution observation",
        "positive_controls": [{"observed": "typed known-satisfactory observation", "rationale": "why it satisfies the original requirement"}],
        "negative_controls": [{"observed": "typed violating observation", "rationale": "which original requirement it violates"}],
    }],
    "input_domain": {"description": "where the check applies"},
    "observation_schema": {"description": "shape of the selected runtime observation"},
    "execution_binding": "exact harness_ref, capability_ref and input_refs from check_design.execution_bindings",
    "limitations": ["what these examples and observations do not establish"],
}


_RETURN_PREREQUISITE_SHAPE = {
    "return_prerequisite": {
        "kind": "returned measurement prerequisite kind",
        "purpose": "its judgment purpose",
        "requirements": ["original specification requirement address"],
    }
}

_FINDING_SHAPE = {"observations": [{
    "requirement": "specification address from investigation_needs",
    "observation_path": "its exact observed quantity",
}]}


def proposal_schemas(role, contribution_requirements):
    from episode_runtime.testing_harness.schema import experiment_schema

    schemas = {
        "choose_part": {
            "one_of": [
                {
                    "assignment": {
                        **_ASSIGNMENT_SHAPE,
                        "goal": (
                            "Precise behavioral contribution. For a nested Parts child, "
                            "prefer a smaller requirement set to give it a distinct part "
                            "of the work. When one requirement covers several steps, "
                            "describe the narrower behavioral contribution here while "
                            "retaining that requirement address."
                        ),
                    },
                    "conflict": "null, or {kind, requirements} for a returned coordination problem",
                    "verification_return_contract": RETURN_SHAPE,
                },
                _RETURN_PREREQUISITE_SHAPE,
            ],
        },
        "design": {
            "one_of": [
                {
                    "plan": {
                        "approach_key": "stable description of this approach",
                        "requirement_mapping": {
                            address: "Explain how this design meets this assigned requirement."
                            for address in contribution_requirements
                        },
                        "intended_change_scope": ["exact editable path"],
                        "dependency_effects": {},
                    },
                    "implementation_return_contract": RETURN_SHAPE,
                    "verification_return_contract": RETURN_SHAPE,
                    "replace_previous": "true to replace the latest returned Implementer for this work; otherwise false",
                },
                {"prerequisite": _prerequisite_shape("designer")},
                _RETURN_PREREQUISITE_SHAPE,
            ],
        },
        "change": {
            "one_of": [
                {
                    "files": [
                        {
                            "logical_path": "assigned path",
                            "content": "complete UTF-8 replacement, or null to remove",
                        }
                    ],
                    "implementation_detail_operations": [
                        {
                            "json_pointer": "an exact permitted materialization target",
                            "before": "current field value",
                            "after": "replacement field value",
                        }
                    ],
                },
                {"prerequisite": _prerequisite_shape("implementer")},
            ],
        },
        "support": {
            "finding": _FINDING_SHAPE
        },
        "question": {
            "one_of": [
                {"finding": _FINDING_SHAPE},
                {"check_review": {
                    "criteria": {"each exact check_design.review_criteria key": {"satisfied": "boolean", "reason": "specific reasoning against the original requirement and proposed cases"}},
                    "counterexamples": ["counterexample showing the check is inadequate; [] only if none found"],
                    "limitations": ["limits and uncertainties retained even when satisfied"],
                }},
            ]
        },
        "measure": {
            "one_of": [
                {"instrument": _MEASURE_SHAPE},
                {"check_design": _CHECK_DESIGN_SHAPE},
                {"submit_reviewed_design": True},
                {"resume_instrument": True},
                {"prerequisite": _prerequisite_shape("measure")},
                {
                    "prerequisite_request": {
                        "kind": "a kind from measure_needs",
                        "purpose": "its judgment purpose",
                        "requirements": ["its specification requirement addresses"],
                        "explanation": (
                            "Briefly identify the missing observation, grounding or capability, "
                            "why the available check-design/acquisition routes cannot supply it, "
                            "and the concrete prerequisite work your parent needs to assign. "
                            "This is your diagnostic reasoning, not a new authority grant."
                        ),
                    }
                },
            ]
        },
    }
    if role == "designer":
        # One scoped example teaches the envelope without duplicating the whole
        # assignment or selecting the Designer's next operation for it.
        example_requirements = list(contribution_requirements[:1])
        schemas["design"]["format_example"] = {
            "guidance": (
                "This example shows the complete JSON nesting for a new local-measure "
                "prerequisite. Choose your operation, purpose, contribution, requested "
                "return and replacement decision from the current assignment and findings. "
                "All child assignment fields, including role and writable_paths, belong "
                "inside prerequisite. Return just the chosen one_of response shape."
            ),
            "response": {
                "prerequisite": {
                    "role": "measure",
                    "goal": "Establish local checks for the selected requirement so implementation progress can be measured.",
                    "requirements": example_requirements,
                    "writable_paths": [],
                    "return_contract": {
                        "decision": "Determine whether local measurement is ready or which prerequisite to resolve next.",
                        "measurements": [],
                        "include": ["measurement_findings", "open_decisions"],
                    },
                    "measure_request": {
                        "purpose": "local",
                        "requirements": example_requirements,
                    },
                    "replace_previous": False,
                    "prerequisites": [],
                },
            },
        }
    tasks = {
        "parts": ("choose_part",),
        "designer": ("design",),
        "implementer": ("change",),
        "verify": (),
        "support": ("support",),
        "question": ("question",),
        "measure": ("measure",),
    }
    result = {name: schemas[name] for name in tasks[role]}
    if role in {"implementer", "verify", "support", "question", "measure"}:
        result["experiment"] = {"one_of": [
            {"evaluation_request_ref": "one exact request from experiment_targets", "experiment": experiment_schema()},
            {"control_target_ref": "one exact grounded control from experiment_targets", "experiment": experiment_schema()},
        ]} if role == "measure" else {
            "evaluation_request_ref": "one exact request from experiment_targets", "experiment": experiment_schema()
        }
    return result


def assign_child(session, call, draft, producer, *, conflict_ref=None,
                 verification_return_contract=None, review_definition=None):
    exact(draft, set(_ASSIGNMENT_SHAPE), "child assignment proposal")
    parent = call.assignment
    role = draft["role"]
    if role not in ROLES[parent.body["role"]].children:
        raise ValueError("only Parts owners may create Designers or nested Parts")
    if not isinstance(draft["goal"], str) or not draft["goal"].strip():
        raise ValueError("child needs a specific behavioral goal")
    need = draft["measure_request"]
    contribution = requirement_keys(session, parent, draft["requirements"])
    if role == "measure":
        exact(need, {"purpose", "requirements"}, "parent measure request")
        if need["purpose"] not in {"local", "acceptance", "composition", "adequacy"}:
            raise ValueError(
                "measure_request.purpose must be one literal category: local, acceptance, "
                "composition, or adequacy; put the behavioral explanation in goal"
            )
        need = {"purpose": need["purpose"], "requirement_keys": requirement_keys(session, parent, need["requirements"])}
        if (
            not need["requirement_keys"]
            or set(need["requirement_keys"])
            != set(contribution)
        ):
            raise ValueError("measure_request.requirements must equal the assignment's requirements")
    elif need is not None:
        raise ValueError("measure requests belong to EstablishMeasure assignments")
    from .measure_needs import assignment_prerequisites
    scope = {
        requirement_address(row) for row in session.requirements
        if row["requirement_key"] in parent.body["scope_requirement_keys"]
    }
    projection = validate_return_contract(draft["return_contract"], scope)
    projection_ref = session.put_data("return_projection", projection)
    if verification_return_contract is not None:
        verification_return_contract = validate_return_contract(verification_return_contract, scope)

    with session.view() as view:
        selected_prerequisites = [
            prerequisite_choice(
                session, view, parent, choice, include_inherited=True
            )
            for choice in draft["prerequisites"]
        ]
        prerequisite_refs = assignment_prerequisites(
            view,
            parent,
            selected_prerequisites,
        )
        slices = owned_slices(view, parent, contribution)
        prior = replacements(view, parent, role, contribution, draft["replace_previous"])
    goal_ref = session.put_data(
        "assigned_goal",
        {
            "goal": draft["goal"],
            "parent_assignment_ref": parent.ref.as_record(),
            "requirement_keys": contribution,
            "producer_ref": producer.as_record(),
            "measure_request": need,
            "verification_return_contract": verification_return_contract,
            **({"prerequisite_refs": prerequisite_refs} if prerequisite_refs else {}),
            **({"measure_review_ref": review_definition} if review_definition is not None else {}),
        },
    )
    body = _thaw_json(parent.body)
    if review_definition is not None:
        body["input_refs"] = [*body["input_refs"], review_definition]
    if prerequisite_refs:
        body["input_refs"] = [
            ref.as_record()
            for ref in dict.fromkeys(
                map(Ref.from_record, [*body["input_refs"], *prerequisite_refs])
            )
        ]
    with session.view() as view:
        body["baseline_candidate_ref"] = view.candidate.ref.as_record()
    body.update({
        "parent_assignment_ref": parent.ref.as_record(),
        "owning_parts_invocation_id": call.invocation_id.value
        if parent.body["role"] == "parts"
        else parent.body["owning_parts_invocation_id"],
        "role": role,
        "goal_record_ref": goal_ref.as_record(),
        "contribution_requirement_keys": contribution,
        "owned_slice_keys": slices,
        "writable_paths": draft["writable_paths"],
        "local_measure_ref": (
            session.policy["measure_admission"]["adequacy_measure_ref"]
            if role == "measure" else parent.body["acceptance_measure_ref"]
            if role == "verify" else parent.body["local_measure_ref"]
        ),
        "acceptance_measure_ref": parent.body["acceptance_measure_ref"],
        "return_projection_ref": projection_ref.as_record(),
        "allowed_child_bindings": list(ROLES[role].children),
        "supersedes_assignment_refs": prior,
    })
    body["judgment_lineage"] = judgment_lineage(body)
    if conflict_ref is not None:
        from .coordination import _affected_branches

        if body["supersedes_assignment_refs"]:
            raise ValueError(
                "joint predecessors are derived from the original conflict"
            )
        with session.view() as view:
            conflict = view.read(Ref.from_record(conflict_ref), "conflict")
            branches = _affected_branches(view, conflict, parent)
        body["supersedes_assignment_refs"] = [
            branch.ref.as_record() for branch in branches
        ]
        body["preservation_requirement_keys"] = sorted({
            *body["preservation_requirement_keys"],
            *(
                key
                for branch in branches
                for key in branch.body["preservation_requirement_keys"]
            ),
        })
    assignment = session.record(call, "assignment", body, producer=producer)
    invocation_id = content_id(
        "refinement_invocation",
        {
            "parent": call.invocation_id.value,
            "unit": call.unit_id.value,
            "assignment": assignment.artifact_id.value,
        },
    )
    session.commit(
        call,
        "assign" if conflict_ref is None else "coordinate_conflict",
        {
            "assignment": assignment.as_record(),
            "invocation_id": invocation_id.value,
            **({"conflict_ref": conflict_ref} if conflict_ref is not None else {}),
        },
        producer=producer,
    )
    return {"role": role, "invocation_id": invocation_id.value}


def _inherited_draft(session, call, role, *, goal, return_contract):
    body = call.assignment.body
    return {
        "role": role,
        "goal": goal,
        "requirements": assigned_addresses(session, call.assignment),
        "writable_paths": list(body["writable_paths"]) if role == "implementer" else [],
        "return_contract": return_contract,
        "measure_request": None,
        "replace_previous": False,
        "prerequisites": [],
    }


def verification_assignment(session, call, purpose):
    from function_library.refinement_contract import verification_return_contract
    role = call.assignment.body["role"]
    expected = "composition" if role == "parts" else "acceptance"
    if role not in {"parts", "designer"} or purpose not in {"baseline", expected}:
        raise ValueError("verification purpose does not belong to this parent")
    if purpose == "baseline":
        projection = verification_return_contract(expected, [
            requirement_address(row) for row in session.requirements
            if row["requirement_key"] in call.assignment.body["scope_requirement_keys"]
        ])
    else:
        with session.view() as view:
            children = [row.record for row in view.entries("assignment")
                        if row.record.invocation_id == call.invocation_id
                        and row.record.logical_unit_id == call.unit_id
                        and row.record.body["role"] in {"implementer", "designer", "parts"}]
            if len(children) != 1:
                raise ValueError("verification needs this unit's explicit parent return request")
            goal = view.data(Ref.from_record(children[0].body["goal_record_ref"]))
            projection = goal["verification_return_contract"]
    return assign_child(
        session,
        call,
        _inherited_draft(
            session,
            call,
            "verify",
            goal=f"Independently determine {expected} against the parent's unchanged requirements.",
            return_contract=projection,
        ),
        session.contract.producer_ref,
    )


def _choose_part(session, call, proposal, producer):
    if "return_prerequisite" in proposal:
        return _return_prerequisite(session, call, proposal, producer)
    exact(proposal, {"assignment", "conflict", "verification_return_contract"}, "part choice")
    with session.view() as view:
        conflict = conflict_choice(session, view, call.assignment, proposal["conflict"])
    return session.reply(
        call,
        child=assign_child(
            session,
            call,
            proposal["assignment"],
            producer,
            conflict_ref=conflict,
            verification_return_contract=proposal["verification_return_contract"],
        ),
    )


def _design(session, call, proposal, producer):
    if "return_prerequisite" in proposal:
        return _return_prerequisite(session, call, proposal, producer)
    if "prerequisite" in proposal:
        return _prerequisite(session, call, proposal, producer)
    fields = {"plan", "implementation_return_contract", "verification_return_contract", "replace_previous"}
    exact(proposal, fields, "design proposal")
    fields = {
        "approach_key",
        "requirement_mapping",
        "intended_change_scope",
        "dependency_effects",
    }
    proposed = exact(proposal["plan"], fields, "design plan")
    scope = assigned_addresses(session, call.assignment, "scope_requirement_keys")
    for field in ("implementation_return_contract", "verification_return_contract"):
        validate_return_contract(proposal[field], scope)
    body = {
        **proposed,
        "requirement_mapping": {
            requirement_keys(session, call.assignment, [address])[0]: meaning
            for address, meaning in proposed["requirement_mapping"].items()
        },
        "assumption_refs": [],
        "proposed_component_refs": [],
        "preservation_measure_refs": [call.assignment.body["acceptance_measure_ref"]],
        "expected_observation_refs": [],
        "falsifying_observation_refs": [],
        "local_measure_ref": call.assignment.body["local_measure_ref"],
        "assignment_ref": call.assignment.ref.as_record(),
        "acceptance_measure_ref": call.assignment.body["acceptance_measure_ref"],
        "open_need_refs": [],
    }
    plan = session.record(call, "design_plan", body, producer=producer)
    session.commit(call, "admit_plan", {"plan": plan.as_record()}, producer=producer)
    draft = _inherited_draft(
        session,
        call,
        "implementer",
        goal="Implement the parent's admitted approach under its fixed local measure.",
        return_contract=proposal["implementation_return_contract"],
    )
    draft["writable_paths"] = list(proposed["intended_change_scope"])
    draft["replace_previous"] = proposal["replace_previous"]
    return session.reply(call, child=assign_child(
        session, call, draft, producer,
        verification_return_contract=proposal["verification_return_contract"],
    ))


def _return_prerequisite(session, call, proposal, producer):
    exact(proposal, {"return_prerequisite"}, "prerequisite return")
    with session.view() as view:
        reference = prerequisite_choice(session, view, call.assignment, proposal["return_prerequisite"])
    session.commit(call, "propose_measure", {"return_prerequisite_ref": reference}, producer=producer)
    return session.reply(call, proceed=False)


def _prerequisite(session, call, proposal, producer):
    exact(proposal, {"prerequisite"}, "prerequisite proposal")
    roles = _PREREQUISITE_ROLES[call.assignment.body["role"]]
    if proposal["prerequisite"]["role"] not in roles:
        raise ValueError(
            "prerequisite child role must be one of: " + ", ".join(roles)
        )
    return session.reply(
        call, child=assign_child(session, call, proposal["prerequisite"], producer)
    )


def _change(session, call, proposal, producer):
    if "prerequisite" in proposal:
        return _prerequisite(session, call, proposal, producer)
    fields = {"files"}
    if "implementation_detail_operations" in proposal:
        fields.add("implementation_detail_operations")
    exact(proposal, fields, "implementation proposal")
    details = proposal.get("implementation_detail_operations", [])
    if (
        not isinstance(proposal["files"], list)
        or not isinstance(details, list)
        or not (proposal["files"] or details)
    ):
        raise ValueError(
            "implementation needs explicit source or permitted plan-detail changes"
        )
    with session.view() as view:
        candidate = view.candidate
        plans = [
            row.record
            for row in view.entries("plan")
            if row.record.body["assignment_ref"]
            == call.assignment.body["parent_assignment_ref"]
        ]
    if not plans:
        raise ValueError("coding cannot precede an admitted parent design")
    operations = []
    for item in proposal["files"]:
        exact(item, {"logical_path", "content"}, "source edit")
        path = logical_path(item["logical_path"])
        if (
            path not in call.assignment.body["writable_paths"]
            or path in call.assignment.body["protected_paths"]
        ):
            raise ValueError("source edit is outside the assigned paths")
        text = item["content"]
        if text is not None and not isinstance(text, str):
            raise ValueError("source content must be UTF-8 text or an explicit removal")
        before = candidate.body["files"].get(path)
        after = (
            session.store.evidence.builds.put_blob(text.encode("utf-8")).value
            if text is not None
            else None
        )
        operations.append({
            "kind": "remove" if text is None else "replace" if before else "add",
            "logical_path": path,
            "before_hash": before,
            "after_blob_hash": after,
        })
    change = session.record(
        call,
        "change",
        {
            "assignment_ref": call.assignment.ref.as_record(),
            "design_plan_ref": plans[-1].ref.as_record(),
            "expected_head_ref": candidate.ref.as_record(),
            "file_operations": operations,
            "implementation_detail_operations": details,
            "rationale_claim_refs": [producer.as_record()],
        },
        producer=producer,
    )
    session.commit(
        call, "apply_change", {"change": change.as_record()}, producer=producer
    )
    return session.reply(call)


def _finding(session, call, proposal, producer):
    from .investigation import needs, selected_checks

    if "check_review" in proposal:
        from .measure_design import assigned_definition

        exact(proposal, {"check_review"}, "check review proposal")
        review = exact(proposal["check_review"], {"criteria", "counterexamples", "limitations"}, "check review")
        with session.view() as view:
            definition = assigned_definition(view, call.assignment)
            if definition is None:
                raise ValueError("this Question has no assigned check definition to review")
        session.commit(call, "propose_measure", {
            "check_review": {"definition_ref": definition.ref.as_record(), **review},
        }, producer=producer)
        return session.reply(call, proceed=False)
    exact(proposal, {"finding"}, "investigation proposal")
    finding = exact(
        proposal["finding"], {"observations"}, "investigation observation choice"
    )
    with session.view() as view:
        available = needs(view, session.policy, call.assignment)
        keys = []
        for choice in finding["observations"]:
            exact(choice, {"requirement", "observation_path"}, "investigation observation")
            requirement = requirement_keys(session, call.assignment, [choice["requirement"]])[0]
            matches = [item["need"]["check_ref"]["artifact_id"] for item in available
                       if item["need"]["requirement_key"] == requirement
                       and view.read(Ref.from_record(item["need"]["check_ref"]), "check").body["observation_path"] == choice["observation_path"]]
            if len(matches) != 1:
                raise ValueError("investigation choice must identify one assigned requirement and observed quantity")
            keys.extend(matches)
        selected_checks(view, session.policy, call.assignment, keys)
    # This records a choice, not a supported finding. Only the common evaluation
    # path obtains observations and projects the parent's fixed decision meaning.
    ref = session.put_data(
        "finding_proposal",
        {
            "assignment_ref": call.assignment.ref.as_record(),
            "producer_ref": producer.as_record(),
            "invocation_id": call.invocation_id.value,
            "logical_unit_id": call.unit_id.value,
            "check_keys": keys,
        },
    )
    return session.reply(call, proposal_ref=ref.as_record())


def _measure(session, call, proposal, producer):
    from .measure_design_runtime import propose_design, propose_reviewed_instrument

    handlers = {
        "check_design": propose_design,
        "submit_reviewed_design": propose_reviewed_instrument,
        "resume_instrument": _resume_measure,
        "prerequisite": _measure_prerequisite,
        "prerequisite_request": _measure_request,
        "instrument": _measure_instrument,
    }
    if len(proposal) != 1 or next(iter(proposal)) not in handlers:
        raise ValueError("select exactly one declared measurement proposal operation")
    return handlers[next(iter(proposal))](session, call, proposal, producer)


def _resume_measure(session, call, proposal, producer):
    if proposal["resume_instrument"] is not True:
        raise ValueError("resume_instrument requires an explicit true")
    with session.view() as view:
        proposals = [row.record for row in view.entries("measure_proposal")
                     if row.record.body["assignment_ref"] == call.assignment.ref.as_record()]
        if not proposals:
            raise ValueError("this assignment has no instrument proposal to resume")
    return session.reply(call, proposal_ref=proposals[-1].ref.as_record())


def _measure_prerequisite(session, call, proposal, producer):
    return _prerequisite(session, call, proposal, producer)


def _measure_request(session, call, proposal, producer):
    from .measure_needs import catalog

    choice = exact(proposal["prerequisite_request"], {"kind", "purpose", "requirements", "explanation"}, "measurement need")
    names((choice["explanation"],), "measurement prerequisite explanation", nonempty=True)
    requirements = requirement_keys(session, call.assignment, choice["requirements"])
    with session.view() as view:
        selected = [need for need in catalog(view, call.assignment, session.policy)
                    if need["kind"] == choice["kind"] and need["purpose"] == choice["purpose"]
                    and set(need["requirement_keys"]) == set(requirements)]
    if len(selected) != 1:
        raise ValueError("measurement request must identify one authorized need by kind, purpose and requirements")
    session.commit(call, "propose_measure", {
        "prerequisite_request": {
            "need_key": selected[0]["need_key"],
            "explanation": choice["explanation"],
        },
    }, producer=producer)
    return session.reply(call, proceed=False)


def _measure_instrument(session, call, proposal, producer):
    exact(proposal, {"instrument"}, "instrument proposal")
    fields = set(_MEASURE_SHAPE)
    for optional in ("instrument_return", "acquired_grounding"):
        if optional not in proposal["instrument"]:
            fields.remove(optional)
    instrument = exact(proposal["instrument"], fields, "instrument contract")
    instrument = {key: value for key, value in instrument.items() if key != "requirements"} | {
        "requirement_keys": requirement_keys(session, call.assignment, instrument["requirements"]),
    }
    constructed = {}
    if "acquired_grounding" in instrument:
        from .grounding import prepare_acquisitions

        instrument, references = prepare_acquisitions(
            session, call.assignment, instrument
        )
        constructed["grounding_acquisition_refs"] = references
    cases = exact(
        instrument["case_manifest"], {"grounding_refs"}, "case manifest proposal"
    )
    manifest_ref = session.put_data("proposed_measure_cases", cases)
    if "instrument_return" in instrument:
        from .instrument_return import prepare_return

        reference = prepare_return(
            session,
            call.assignment,
            instrument["instrument_return"],
            instrument,
            acquisition_refs=constructed.get("grounding_acquisition_refs", ()),
        )
        constructed["instrument_return_ref"] = reference.as_record()
    record = session.record(
        call,
        "measure_proposal",
        {
            "assignment_ref": call.assignment.ref.as_record(),
            "owner_assignment_ref": call.assignment.body["parent_assignment_ref"],
            **{
                key: value
                for key, value in instrument.items()
                if key not in {"case_manifest", "instrument_return"}
            },
            "case_manifest_ref": manifest_ref.as_record(),
            **constructed,
        },
        producer=producer,
    )
    session.commit(
        call, "propose_measure", {"proposal": record.as_record()}, producer=producer
    )
    return session.reply(call, proposal_ref=record.ref.as_record())


_HANDLERS = {
    "choose_part": _choose_part,
    "design": _design,
    "change": _change,
    "support": _finding,
    "question": _finding,
    "measure": _measure,
}


def admit_proposal(session, call, task, proposal, producer):
    if task not in proposal_schemas(
        call.assignment.body["role"], assigned_addresses(session, call.assignment)
    ):
        raise ValueError("proposal task does not belong to this role")
    if task == "experiment":
        from .evaluation_experiments import propose_experiment

        return propose_experiment(
            session.evaluations, session, call, proposal, producer
        )
    return _HANDLERS[task](session, call, proposal, producer)
