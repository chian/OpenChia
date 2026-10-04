"""Task-specific proposals admitted by the one refinement host session.

Models supply the behavioral choice, design, or source text. The host supplies
identity, authority, inherited constraints, candidate hashes and final records.
"""

from agent.duet_contracts import content_id
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json
from function_library.refinement_contract import ROLES

from .records import Ref, logical_path
from .state_machine import judgment_lineage


_ASSIGNMENT_SHAPE = {
    "role": "one permitted child role",
    "goal": "precise behavioral contribution, not a file grouping",
    "contribution_requirement_keys": ["original requirement key"],
    "owned_slice_keys": ["a parent's declared slice key"],
    "writable_paths": ["an exact path within the parent's editable scope"],
    "local_measure_ref": {
        "artifact_id": "an admitted measure",
        "content_hash": "its exact hash",
    },
    "acceptance_measure_ref": {
        "artifact_id": "an admitted acceptance measure",
        "content_hash": "its exact hash",
    },
    "measure_request": "null except for EstablishMeasure: {purpose, requirement_keys}",
    "supersedes_assignment_refs": [
        {
            "artifact_id": "returned direct-child assignment ID; use [] for new work",
            "content_hash": "its exact hash",
        }
    ],
    "prerequisite_refs": [
        {
            "artifact_id": "original returned measurement-request ID; use [] if none",
            "content_hash": "its exact hash",
        }
    ],
}

_MEASURE_SHAPE = {
    "requirement_keys": ["the parent's exact requested requirement keys"],
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


def proposal_schemas(role):
    from episode_runtime.testing.schema import experiment_schema

    schemas = {
        "choose_part": {
            "assignment": _ASSIGNMENT_SHAPE,
            "conflict_ref": "null, or the exact conflict reference for a joint repair",
        },
        "design": {
            "one_of": [
                {
                    "plan": {
                        "approach_key": "stable description of this approach",
                        "requirement_mapping": {
                            "each exact assignment contribution_requirement_keys entry": (
                                "how the design meets it; include every contribution key "
                                "and no other keys, including preservation-only keys"
                            )
                        },
                        "intended_change_scope": ["exact editable path"],
                        "assumption_refs": [],
                        "proposed_component_refs": [],
                        "dependency_effects": {},
                        "preservation_measure_refs": [],
                        "expected_observation_refs": [],
                        "falsifying_observation_refs": [],
                        "local_measure_ref": "exact admitted measure for the Implementer's own loop",
                    },
                    "supersedes_assignment_refs": [
                        {
                            "artifact_id": "returned Implementer assignment ID; use [] if none",
                            "content_hash": "its exact hash",
                        }
                    ],
                },
                {"prerequisite": _ASSIGNMENT_SHAPE},
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
                {"prerequisite": _ASSIGNMENT_SHAPE},
            ],
        },
        "support": {
            "finding": {"check_keys": ["select exact checks from investigation_needs"]}
        },
        "question": {
            "finding": {"check_keys": ["select exact checks from investigation_needs"]}
        },
        "measure": {
            "one_of": [
                {"instrument": _MEASURE_SHAPE},
                {"resume_proposal_ref": "an existing exact measure_proposals reference owned by this assignment; continue selecting its remaining controls"},
                {"prerequisite": _ASSIGNMENT_SHAPE},
                {
                    "prerequisite_request": {
                        "need_key": "select an exact key from measure_needs"
                    }
                },
            ]
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


def assign_child(session, call, draft, producer, *, conflict_ref=None):
    fields = set(_ASSIGNMENT_SHAPE)
    for optional in ("supersedes_assignment_refs", "prerequisite_refs"):
        if optional not in draft:
            fields.remove(optional)
    exact(draft, fields, "child assignment proposal")
    parent = call.assignment
    role = draft["role"]
    if role not in ROLES[parent.body["role"]].children:
        raise ValueError("only Parts owners may create Designers or nested Parts")
    if not isinstance(draft["goal"], str) or not draft["goal"].strip():
        raise ValueError("child needs a specific behavioral goal")
    need = draft["measure_request"]
    if role == "measure":
        exact(need, {"purpose", "requirement_keys"}, "parent measure request")
        if (
            need["purpose"] not in {"local", "acceptance", "composition", "adequacy"}
            or not need["requirement_keys"]
            or set(need["requirement_keys"])
            != set(draft["contribution_requirement_keys"])
        ):
            raise ValueError("EstablishMeasure needs the parent's exact judgment scope")
    elif need is not None:
        raise ValueError("measure requests belong to EstablishMeasure assignments")
    from .measure_needs import assignment_prerequisites

    with session.view() as view:
        prerequisite_refs = assignment_prerequisites(
            view,
            parent,
            draft.get("prerequisite_refs", ()),
            draft["contribution_requirement_keys"],
        )
    goal_ref = session.put_data(
        "assigned_goal",
        {
            "goal": draft["goal"],
            "parent_assignment_ref": parent.ref.as_record(),
            "requirement_keys": draft["contribution_requirement_keys"],
            "producer_ref": producer.as_record(),
            "measure_request": need,
            **({"prerequisite_refs": prerequisite_refs} if prerequisite_refs else {}),
        },
    )
    body = _thaw_json(parent.body)
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
        "contribution_requirement_keys": draft["contribution_requirement_keys"],
        "owned_slice_keys": draft["owned_slice_keys"],
        "writable_paths": draft["writable_paths"],
        "local_measure_ref": draft["local_measure_ref"],
        "acceptance_measure_ref": draft["acceptance_measure_ref"],
        "allowed_child_bindings": list(ROLES[role].children),
        "supersedes_assignment_refs": draft.get("supersedes_assignment_refs", []),
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


def _inherited_draft(call, role, *, goal, measure=None):
    body = call.assignment.body
    return {
        "role": role,
        "goal": goal,
        "contribution_requirement_keys": list(body["contribution_requirement_keys"]),
        "owned_slice_keys": list(body["owned_slice_keys"]),
        "writable_paths": list(body["writable_paths"]) if role == "implementer" else [],
        "local_measure_ref": _thaw_json(measure or body["local_measure_ref"]),
        "acceptance_measure_ref": _thaw_json(body["acceptance_measure_ref"]),
        "measure_request": None,
        "supersedes_assignment_refs": [],
    }


def verification_assignment(session, call, purpose):
    role = call.assignment.body["role"]
    expected = "composition" if role == "parts" else "acceptance"
    if role not in {"parts", "designer"} or purpose not in {"baseline", expected}:
        raise ValueError("verification purpose does not belong to this parent")
    return assign_child(
        session,
        call,
        _inherited_draft(
            call,
            "verify",
            goal=f"Independently determine {expected} against the parent's unchanged requirements.",
            measure=call.assignment.body["acceptance_measure_ref"],
        ),
        session.contract.producer_ref,
    )


def _choose_part(session, call, proposal, producer):
    exact(proposal, {"assignment", "conflict_ref"}, "part choice")
    return session.reply(
        call,
        child=assign_child(
            session,
            call,
            proposal["assignment"],
            producer,
            conflict_ref=proposal["conflict_ref"],
        ),
    )


def _design(session, call, proposal, producer):
    if "prerequisite" in proposal:
        return _prerequisite(
            session, call, proposal, producer, {"support", "question", "measure"}
        )
    fields = {"plan"}
    if "supersedes_assignment_refs" in proposal:
        fields.add("supersedes_assignment_refs")
    exact(proposal, fields, "design proposal")
    fields = {
        "approach_key",
        "requirement_mapping",
        "intended_change_scope",
        "assumption_refs",
        "proposed_component_refs",
        "dependency_effects",
        "preservation_measure_refs",
        "expected_observation_refs",
        "falsifying_observation_refs",
        "local_measure_ref",
    }
    proposed = exact(proposal["plan"], fields, "design plan")
    body = {
        **proposed,
        "assignment_ref": call.assignment.ref.as_record(),
        "acceptance_measure_ref": call.assignment.body["acceptance_measure_ref"],
        "open_need_refs": [],
    }
    plan = session.record(call, "design_plan", body, producer=producer)
    session.commit(call, "admit_plan", {"plan": plan.as_record()}, producer=producer)
    draft = _inherited_draft(
        call,
        "implementer",
        goal="Implement the parent's admitted approach under its fixed local measure.",
        measure=proposed["local_measure_ref"],
    )
    draft["writable_paths"] = list(proposed["intended_change_scope"])
    draft["supersedes_assignment_refs"] = proposal.get("supersedes_assignment_refs", [])
    return session.reply(call, child=assign_child(session, call, draft, producer))


def _prerequisite(session, call, proposal, producer, roles):
    exact(proposal, {"prerequisite"}, "prerequisite proposal")
    if proposal["prerequisite"]["role"] not in roles:
        raise ValueError("this role cannot use that child as a prerequisite")
    return session.reply(
        call, child=assign_child(session, call, proposal["prerequisite"], producer)
    )


def _change(session, call, proposal, producer):
    if "prerequisite" in proposal:
        return _prerequisite(session, call, proposal, producer, {"question"})
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
    from .investigation import selected_checks

    exact(proposal, {"finding"}, "investigation proposal")
    finding = exact(
        proposal["finding"], {"check_keys"}, "investigation observation choice"
    )
    with session.view() as view:
        selected_checks(view, session.policy, call.assignment, finding["check_keys"])
    # This records a choice, not a supported finding. Only the common evaluation
    # path obtains observations and projects the parent's fixed decision meaning.
    ref = session.put_data(
        "finding_proposal",
        {
            "assignment_ref": call.assignment.ref.as_record(),
            "producer_ref": producer.as_record(),
            "invocation_id": call.invocation_id.value,
            "logical_unit_id": call.unit_id.value,
            **finding,
        },
    )
    return session.reply(call, proposal_ref=ref.as_record())


def _measure(session, call, proposal, producer):
    if "resume_proposal_ref" in proposal:
        exact(proposal, {"resume_proposal_ref"}, "continued measure proposal")
        reference = Ref.from_record(proposal["resume_proposal_ref"])
        with session.view() as view:
            prior = view.entry("measure_proposal", reference.artifact_id.value).record
            if prior.ref != reference or prior.body["assignment_ref"] != call.assignment.ref.as_record():
                raise ValueError("continued measure proposal belongs to another assignment")
        return session.reply(call, proposal_ref=reference.as_record())
    if "prerequisite" in proposal:
        return _prerequisite(session, call, proposal, producer, {"question"})
    if "prerequisite_request" in proposal:
        exact(proposal, {"prerequisite_request"}, "measurement prerequisite proposal")
        session.commit(call, "propose_measure", proposal, producer=producer)
        return session.reply(call, proceed=False)
    exact(proposal, {"instrument"}, "instrument proposal")
    fields = set(_MEASURE_SHAPE)
    for optional in ("instrument_return", "acquired_grounding"):
        if optional not in proposal["instrument"]:
            fields.remove(optional)
    instrument = exact(proposal["instrument"], fields, "instrument contract")
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
    if task not in proposal_schemas(call.assignment.body["role"]):
        raise ValueError("proposal task does not belong to this role")
    if task == "experiment":
        from .evaluation_experiments import propose_experiment

        return propose_experiment(
            session.evaluations, session, call, proposal, producer
        )
    return _HANDLERS[task](session, call, proposal, producer)
