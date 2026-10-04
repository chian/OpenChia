"""Project independently acquired evidence into parent-authorized measure cases.

The frozen template owns the criterion. A returned question can supply only its
expected value and control inputs, from an explicitly approved read-only source.
No model-authored interpretation or raw instruction becomes authority here.
"""

from dataclasses import dataclass

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact
from function_library.refinement_checks import GROUNDING_PAYLOAD, grounding_payload

from .checking import reference_definition
from .measure_needs import admission_policy
from .records import EvidenceRef, Ref, RefinementRecord


CASE_FIELDS = {
    "requirement_key",
    "purpose",
    "expected",
    "observation_path",
    "dependency_paths",
    "environment_ref",
    "oracle_ref",
    "input_domain_ref",
    "observation_schema_ref",
    "decision_function_ref",
    "independence_policy_ref",
    "uncertainty_policy_ref",
    "limitation_refs",
    "positive_control_refs",
    "negative_control_refs",
    "execution_binding",
    "guard_keys",
}
_ACQUIRED_FIELDS = {"expected", "positive_control_refs", "negative_control_refs"}


def specification(view, reference):
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    grant = admission_policy(policy)
    if reference not in set(
        map(Ref.from_record, (grant or {}).get("acquisition_refs", ()))
    ):
        raise ValueError(
            "grounding acquisition lacks exact frozen source/projection authority"
        )
    spec = exact(
        view.data(reference),
        {"need_ref", "case_template_ref", "source_ref", "control_kind"},
        "grounding acquisition",
    )
    if spec["control_kind"] not in {"predicate", "execution"}:
        raise ValueError("grounding acquisition has an unsupported control kind")
    if spec["need_ref"] not in policy.get("investigation_need_refs", ()):
        raise ValueError("grounding acquisition must use an authorized question need")
    need = view.data(Ref.from_record(spec["need_ref"]))
    template = exact(
        view.data(Ref.from_record(spec["case_template_ref"])),
        CASE_FIELDS - _ACQUIRED_FIELDS,
        "grounded case template",
    )
    if (
        need["role"] != "question"
        or need["outcomes"]["pass"] != "supported"
        or need["requirement_key"] != template["requirement_key"]
        or template["environment_ref"] != view.contract.body["environment_ref"]
    ):
        raise ValueError(
            "grounding acquisition changes its requirement or applicability"
        )
    view.data(Ref.from_record(spec["source_ref"]))
    return spec, need, template


def acquired_value(view, selection, requester):
    """Original returned evidence is required; selecting a need is not evidence."""
    from .measures import _within_owner

    exact(
        selection,
        {"acquisition_ref", "report_ref", "observation_ref"},
        "acquired grounding selection",
    )
    spec, need, template = specification(
        view, Ref.from_record(selection["acquisition_ref"])
    )
    report_ref = Ref.from_record(selection["report_ref"])
    report = view.entry("report", report_ref.artifact_id.value).record
    invocation = view.entry("invocation", report.invocation_id.value)
    assignment = invocation.record
    observation = view.read(
        Ref.from_record(selection["observation_ref"]), "observation"
    )
    if (
        report.ref != report_ref
        or report.body["assignment_ref"] != assignment.ref.as_record()
        or assignment.body["role"] != "question"
        or invocation.status not in {"returned", "superseded"}
        or observation.invocation_id != report.invocation_id
        or observation.body["check_key"] != need["check_ref"]["artifact_id"]
        or observation.body["outcome"] != "pass"
        or not observation.evidence_refs
        or not _within_owner(view, assignment.body["parent_assignment_ref"], requester)
    ):
        raise ValueError(
            "acquired grounding lacks an owned, successful ResolveQuestion return"
        )
    if not any(
        finding["need_ref"] == spec["need_ref"]
        and finding["observation_ref"] == observation.ref.as_record()
        and finding["state"] == "supported"
        and finding["resolved"]
        for finding in report.body.get("investigation_findings", ())
    ):
        raise ValueError("the question report did not establish this grounding result")
    check = view.read(Ref.from_record(need["check_ref"]), "check")
    predicate = view.data(Ref.from_record(check.body["predicate_ref"]))
    if (
        predicate["definition_id"] != GROUNDING_PAYLOAD.definition_id
        or predicate["library"] != GROUNDING_PAYLOAD.library
        or check.body["expected"] != {"control_kind": spec["control_kind"]}
    ):
        raise ValueError(
            "acquisition must retain its registered result shape, not a model verdict"
        )
    request = view.read(Ref.from_record(observation.body["request_ref"]), "evaluation")
    harness = view.data(Ref.from_record(request.body["harness_ref"]))
    definition = reference_definition(view.data, view.contract, request.body)
    if (
        definition is None
        or harness["reference_ref"] != spec["source_ref"]
        or request.body["measure_ref"] != need["measure_ref"]
        or request.body["purpose"] != "question"
    ):
        raise ValueError("grounding was not acquired from the exact independent source")
    source = view.entry("evaluation_source", request.artifact_id.value)
    if source.status != "admitted" or canonical_json(
        view.data(Ref.from_record(source.record.body["build_receipt_ref"]))
    ) != canonical_json(view.data(Ref.from_record(definition["build_receipt_ref"]))):
        raise ValueError(
            "grounding source differs from its independently approved build"
        )
    observed = observation.body["observed_value"]
    if grounding_payload(observed=observed, expected=check.body["expected"]) != "pass":
        raise ValueError(
            "acquired grounding is incomplete or has contradictory controls"
        )
    return template, observed, observation


def controls(observed):
    return {
        field: [
            {**value, "expected_outcome": outcome} for value in observed[input_field]
        ]
        for field, input_field, outcome in (
            ("positive_control_refs", "positive_controls", "pass"),
            ("negative_control_refs", "negative_controls", "fail"),
        )
    }


def prepare_acquisitions(session, assignment, instrument):
    """Fill only the values delegated to the authorized evidence provider."""
    selections = instrument.get("acquired_grounding", ())
    if not isinstance(selections, (list, tuple)) or not selections:
        raise ValueError("acquired grounding must select original returned evidence")
    if len({canonical_json(item) for item in selections}) != len(selections):
        raise ValueError("one measure cannot repeat an acquisition")
    prepared = []
    for selection in selections:
        with session.view() as view:
            template, observed, _ = acquired_value(view, selection, assignment)
        projected = {
            field: [
                session.put_data("independent_grounding_control", value).as_record()
                for value in values
            ]
            for field, values in controls(observed).items()
        }
        case = {**template, "expected": observed["expected"], **projected}
        case_ref = session.put_data("acquired_grounding_case", case)
        bundle_ref = session.put_data(
            "grounding_acquisition", {**selection, "case_ref": case_ref.as_record()}
        )
        prepared.append((bundle_ref, case_ref, case))
    body = {
        key: value for key, value in instrument.items() if key != "acquired_grounding"
    }
    body["case_manifest"] = {
        "grounding_refs": list(instrument["case_manifest"]["grounding_refs"])
    }
    for field in (
        "grounding_refs",
        "positive_control_refs",
        "negative_control_refs",
        "limitation_refs",
    ):
        original = list(instrument[field])
        added = (
            [ref.as_record() for _, ref, _ in prepared]
            if field == "grounding_refs"
            else [ref for _, _, case in prepared for ref in case[field]]
        )
        body[field] = [
            ref.as_record()
            for ref in dict.fromkeys(map(Ref.from_record, [*original, *added]))
        ]
    body["case_manifest"]["grounding_refs"] = [
        ref.as_record()
        for ref in dict.fromkeys(
            map(
                Ref.from_record,
                [
                    *body["case_manifest"]["grounding_refs"],
                    *(ref.as_record() for _, ref, _ in prepared),
                ],
            )
        )
    ]
    return body, [ref.as_record() for ref, _, _ in prepared]


@dataclass(frozen=True)
class AcquiredGrounding:
    case_refs: tuple[Ref, ...] = ()
    acquisition_refs: tuple[Ref, ...] = ()
    provenance_refs: tuple[Ref, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    observations: tuple[RefinementRecord, ...] = ()


def authorize_acquisitions(view, body):
    requester = view.read(Ref.from_record(body["assignment_ref"]), "assignment")
    cases, acquisitions, provenance, evidence, observations = [], [], [], [], []
    for raw in body.get("grounding_acquisition_refs", ()):
        bundle_ref = Ref.from_record(raw)
        bundle = exact(
            view.data(bundle_ref),
            {"acquisition_ref", "report_ref", "observation_ref", "case_ref"},
            "grounding acquisition bundle",
        )
        selection = {
            key: bundle[key]
            for key in ("acquisition_ref", "report_ref", "observation_ref")
        }
        template, observed, observation = acquired_value(view, selection, requester)
        case_ref = Ref.from_record(bundle["case_ref"])
        case = exact(view.data(case_ref), CASE_FIELDS, "acquired grounded case")
        if canonical_json({key: case[key] for key in template}) != canonical_json(
            template
        ) or canonical_json(case["expected"]) != canonical_json(observed["expected"]):
            raise ValueError(
                "acquired grounding changed its original criterion or evidence projection"
            )
        for field, expected in controls(observed).items():
            actual = [view.data(Ref.from_record(ref)) for ref in case[field]]
            if canonical_json(actual) != canonical_json(expected):
                raise ValueError(
                    "acquired controls differ from original independent evidence"
                )
        if case_ref.as_record() not in body["grounding_refs"] or case_ref in cases:
            raise ValueError(
                "acquisition is unused or duplicates an existing complete case"
            )
        cases.append(case_ref)
        acquisitions.append(Ref.from_record(bundle["acquisition_ref"]))
        provenance.extend((
            bundle_ref,
            *(Ref.from_record(value) for value in selection.values()),
        ))
        evidence.extend(observation.evidence_refs)
        observations.append(observation)
    return AcquiredGrounding(
        tuple(cases),
        tuple(acquisitions),
        tuple(dict.fromkeys(provenance)),
        tuple(dict.fromkeys(evidence)),
        tuple({record.ref: record for record in observations}.values()),
    )


def grounding_context(view, assignment, policy):
    grant = admission_policy(policy) or {}
    scope = set(assignment.body["scope_requirement_keys"])
    acquisitions, available = [], []
    for raw in grant.get("acquisition_refs", ()):
        reference = Ref.from_record(raw)
        spec, need, template = specification(view, reference)
        if template["requirement_key"] not in scope:
            continue
        acquisitions.append({
            "reference": raw,
            "specification": spec,
            "case_template": template,
            "need": need,
        })
        for row in reversed(view.entries("report")):
            for finding in row.record.body.get("investigation_findings", ()):
                if (
                    finding["need_ref"] != spec["need_ref"]
                    or finding["state"] != "supported"
                ):
                    continue
                selection = {
                    "acquisition_ref": raw,
                    "report_ref": row.record.ref.as_record(),
                    "observation_ref": finding["observation_ref"],
                }
                try:
                    acquired_value(view, selection, assignment)
                except ValueError:
                    continue
                available.append(selection)
                break
            else:
                continue
            break
    return {
        "measure_grounding": [
            {"reference": ref, "case": view.data(Ref.from_record(ref))}
            for ref in grant.get("grounding_refs", ())
            if view.data(Ref.from_record(ref))["requirement_key"] in scope
        ],
        "grounding_acquisitions": acquisitions,
        "acquired_grounding": available,
    }
