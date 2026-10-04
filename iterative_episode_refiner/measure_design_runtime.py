"""Model-facing design/review operations and their exact measure projection."""

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact

from .campaign_store import CampaignStore
from .measure_design import reviewed
from .records import Ref


def propose_design(session, call, proposal, producer):
    from .runtime_proposals import _inherited_draft, assign_child
    from function_library.refinement_contract import check_review_return_contract
    from .assignment_choices import requirement_keys

    design = proposal["check_design"]
    cases = []
    for case in design["cases"]:
        if "requirement_key" in case:
            raise ValueError("check design requires specification requirement locations")
        cases.append({
            **{key: value for key, value in case.items() if key != "requirement"},
            "requirement_key": requirement_keys(session, call.assignment, [case["requirement"]])[0],
        })
    session.commit(call, "propose_measure", {
        "check_design": {**design, "cases": cases},
    }, producer=producer)
    with session.view() as view:
        definitions = [
            row.record
            for row in view.entries("measure_definition")
            if row.record.invocation_id == call.invocation_id
            and row.record.logical_unit_id == call.unit_id
        ]
    definition = definitions[-1]
    draft = _inherited_draft(
        session,
        call,
        "question",
        goal="Review this exact proposed check against the original requirement. Challenge expected results, observation relevance and each control's polarity; return criteria, counterexamples and limitations, not target success or credit.",
        return_contract=check_review_return_contract(),
    )
    return session.reply(call, child=assign_child(
        session, call, draft, producer, review_definition=definition.ref.as_record(),
    ))


def project(view, assignment, reference, data):
    definition, reviews = reviewed(view, reference, assignment)
    design = definition.body["design"]
    origin = data(
        "reviewed_check_origin",
        {
            "definition_ref": definition.ref.as_record(),
            "review_refs": [review.ref.as_record() for review in reviews],
            "requirement_catalog_ref": definition.body["requirement_catalog_ref"],
            "basis": "Parent-delegated reasoning reviewed in a separate invocation; not independent empirical truth.",
        },
    )
    limitations = list(
        dict.fromkeys([
            *design["limitations"],
            *(text for review in reviews for text in review.body["limitations"]),
            "Controls establish discrimination on the reviewed examples, not complete coverage or Target Workflow correctness.",
        ])
    )
    common = {
        "purpose": design["purpose"],
        "oracle_ref": origin.as_record(),
        "input_domain_ref": data("measure_domain", design["input_domain"]).as_record(),
        "observation_schema_ref": data(
            "measure_schema", design["observation_schema"]
        ).as_record(),
        "decision_function_ref": data("predicate", design["predicate"]).as_record(),
        "independence_policy_ref": data(
            "measure_independence",
            {
                "basis": "Separate assigned check review followed by host-executed controls; shared models may share errors."
            },
        ).as_record(),
        "uncertainty_policy_ref": data(
            "measure_uncertainty", {"limitations": limitations}
        ).as_record(),
        "limitation_refs": [
            data("measure_limitation", {"text": text}).as_record()
            for text in limitations
        ],
    }
    cases, positives, negatives = [], {}, {}
    for case in design["cases"]:
        controls = {}
        for field, polarity, collected in (
            ("positive", "pass", positives),
            ("negative", "fail", negatives),
        ):
            values = [
                data(
                    "grounding_control",
                    {"observed": item["observed"], "expected_outcome": polarity},
                )
                for item in case[f"{field}_controls"]
            ]
            controls[f"{field}_control_refs"] = [ref.as_record() for ref in values]
            collected.update({ref: None for ref in values})
        cases.append(
            data(
                "grounded_case",
                {
                    **common,
                    **controls,
                    "requirement_key": case["requirement_key"],
                    "expected": case["expected"],
                    "observation_path": case["observation_path"],
                    "dependency_paths": None,
                    "environment_ref": view.contract.body["environment_ref"],
                    "execution_binding": design["execution_binding"],
                    "guard_keys": [],
                },
            )
        )
    return {
        **common,
        "requirement_keys": sorted({
            case["requirement_key"] for case in design["cases"]
        }),
        "oracle_kind": "registered_predicate",
        "positive_control_refs": [ref.as_record() for ref in positives],
        "negative_control_refs": [ref.as_record() for ref in negatives],
        "grounding_refs": [ref.as_record() for ref in cases],
        "case_manifest_ref": data(
            "proposed_measure_cases",
            {"grounding_refs": [ref.as_record() for ref in cases]},
        ).as_record(),
        "reviewed_definition_ref": definition.ref.as_record(),
    }


def propose_reviewed_instrument(session, call, proposal, producer):
    exact(proposal, {"submit_reviewed_design"}, "reviewed check selection")
    if proposal["submit_reviewed_design"] is not True:
        raise ValueError("submit_reviewed_design requires an explicit true")
    # Pure projection first; writes use the existing content-addressed store
    # outside the read transaction, then ordinary measure admission rechecks it.
    artifacts = []

    def collect(kind, value):
        artifacts.append((kind, value))
        return CampaignStore.data_reference(session.duet_id, kind, value)

    with session.view() as view:
        definitions = [row.record for row in view.entries("measure_definition")
                       if row.record.body["assignment_ref"] == call.assignment.ref.as_record()]
        if not definitions:
            raise ValueError("this assignment has no check design to submit")
        body = project(
            view, call.assignment, definitions[-1].ref.as_record(), collect
        )
    for kind, value in artifacts:
        session.put_data(kind, value)
    record = session.record(
        call,
        "measure_proposal",
        {
            "assignment_ref": call.assignment.ref.as_record(),
            "owner_assignment_ref": call.assignment.body["parent_assignment_ref"],
            **body,
        },
        producer=producer,
    )
    session.commit(
        call, "propose_measure", {"proposal": record.as_record()}, producer=producer
    )
    return session.reply(call, proposal_ref=record.ref.as_record())


def authorize(view, proposal):
    reference = proposal.body.get("reviewed_definition_ref")
    if reference is None:
        return ()
    assignment = view.read(
        Ref.from_record(proposal.body["assignment_ref"]), "assignment"
    )

    def verified_data(kind, value):
        ref = CampaignStore.data_reference(view.head["duet_id"], kind, value)
        if canonical_json(view.data(ref)) != canonical_json(value):
            raise ValueError("reviewed case projection changed")
        return ref

    expected = project(view, assignment, reference, verified_data)
    actual = {
        key: value
        for key, value in proposal.body.items()
        if key not in {"assignment_ref", "owner_assignment_ref"}
    }
    if canonical_json(actual) != canonical_json(expected):
        raise ValueError("measure differs from the exact reviewed check definition")
    return tuple(map(Ref.from_record, expected["grounding_refs"]))
