"""Evidence-backed testing findings, admitted through the existing learning ledger."""

import json

from .epistemic_admission import _evidence, admit_candidates
from .epistemic_schemas import canonical, identity
from .models import _thaw_json


MEASUREMENT_KIND = "experiment_measurement"


def _measured_entity(body, contract, scope, evidence):
    if tuple(contract.required_fields) != ("measurement",) or tuple(
        contract.required_evidence
    ) != (MEASUREMENT_KIND,):
        raise ValueError("testing admission requires the exact measurement contract")
    if set(body["fields"]) != {"measurement"} or len(body["evidence"]) != 1:
        raise ValueError("a testing finding must name one complete measured outcome")
    link = body["evidence"][0]
    source = _evidence([link["ref"]], evidence)[0]
    if (
        source["schema_id"] != "openchia.experiment-measurement"
        or link["kind"] != MEASUREMENT_KIND
        or source["body"]["kind"] != MEASUREMENT_KIND
        or link["quote"] not in source["body"]["text"]
    ):
        raise ValueError(
            "testing knowledge requires host-projected experimental evidence"
        )
    observation = source["body"]["observation"]
    if observation["status"] not in {"pass", "fail"}:
        raise ValueError(
            "unmeasured or inconclusive execution cannot resolve a requirement"
        )
    try:
        proposed = json.loads(body["fields"]["measurement"])
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "measurement must encode the complete typed observation"
        ) from exc
    if canonical(proposed) != canonical(observation):
        raise ValueError("proposed finding differs from the host-measured observation")
    # Rewording predictions, new Run IDs, or another numerical value with the
    # same verdict do not resolve another requirement. Pass and fail each mean
    # 'observed under this context', never a universal correctness assertion.
    key = identity(
        "entity",
        {
            "scope": scope,
            "subject": observation["subject"],
            "status": observation["status"],
        },
    )
    admitted = {
        "key": key,
        "fields": {"measurement": canonical(observation).decode()},
        "evidence": [_thaw_json(link)],
        "answer_contract": {
            "answer_forms": ["Host-measured requirement outcome"],
            "acceptance_tests": [
                "Exact registered criterion on the recorded candidate and context"
            ],
            "falsification_tests": [
                "Contrary measurement under the same criterion and context"
            ],
        },
        "uncertainties": list(observation["limitations"]),
    }
    return key, admitted, (link["ref"],)


def admit_testing_findings(**kwargs):
    if any(candidate["kind"] != "entity" for candidate in kwargs["candidates"]):
        raise ValueError(
            "testing findings cannot promote prose lessons or revise criteria"
        )
    return admit_candidates(**kwargs, entity_admitter=_measured_entity)


def project_testing_findings(state):
    findings = [record for record in state["records"] if record["status"] == "active"]
    return {
        "established_results": findings,
        "unresolved_questions": sorted({
            question
            for record in findings
            for question in record["body"]["uncertainties"]
        }),
        "acceptance_granted": False,
    }
