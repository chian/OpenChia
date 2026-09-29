from __future__ import annotations

import copy

import pytest

from agent.episode_contracts import OpaqueId, Sha256Digest
from agent.generic_creator_models import (
    EvidenceGate,
    EvidenceGateManifest,
    GateAcceptanceState,
    GateRequirement,
    GenericCreatorInstanceSpec,
    GenericCreatorType,
)
from agent.generic_creator_templates import (
    select_rarefaction_candidate,
    validate_template_result,
    validate_template_spec,
)
from tests.agent.generic_creator_fixtures import creator_spec


@pytest.mark.parametrize("creator_type", list(GenericCreatorType))
def test_every_generic_creator_template_validates(creator_type: GenericCreatorType) -> None:
    spec = creator_spec(creator_type.value, creator_type=creator_type)
    assert validate_template_spec(spec).creator_type is creator_type
    assert GenericCreatorInstanceSpec.from_record(spec.as_record()) == spec


def test_instance_schema_rejects_unknown_security_field() -> None:
    record = creator_spec().as_record()
    record["mint_capabilities"] = True
    with pytest.raises(ValueError, match="unknown=.*mint_capabilities"):
        GenericCreatorInstanceSpec.from_record(record)


def test_template_rejects_missing_and_unknown_fields() -> None:
    record = creator_spec().as_record()
    definition = dict(record["work_definition"])
    definition.pop("stable_task_goal")
    definition["domain_specific_bypass"] = True
    record["work_definition"] = definition
    spec = GenericCreatorInstanceSpec.from_record(record)
    with pytest.raises(ValueError, match="stable_task_goal"):
        validate_template_spec(spec)


def _gate(gate_id: str, dependencies: tuple[str, ...] = ()) -> EvidenceGate:
    return EvidenceGate(
        gate_id, gate_id, 1.0, "test_result", "host_test", 1,
        dependencies, GateRequirement.REQUIRED, GateAcceptanceState.PENDING, (),
    )


def test_gate_manifest_accepts_converging_dag_and_rejects_cycle() -> None:
    EvidenceGateManifest(
        "manifest", 1, Sha256Digest.of_bytes(b"criteria"),
        (_gate("a"), _gate("b", ("a",)), _gate("c", ("a",)), _gate("d", ("b", "c"))),
    )
    with pytest.raises(ValueError, match="acyclic"):
        EvidenceGateManifest(
            "cycle", 1, Sha256Digest.of_bytes(b"criteria"),
            (_gate("a", ("b",)), _gate("b", ("a",))),
        )


def test_model_cannot_mark_gate_accepted_without_evidence() -> None:
    with pytest.raises(ValueError, match="minimum accepted evidence"):
        EvidenceGate(
            "gate", "gate", 1, "test_result", "host_test", 1, (),
            GateRequirement.REQUIRED, GateAcceptanceState.ACCEPTED, (),
        )


def test_rarefaction_selects_unique_marginal_yield_and_can_stop() -> None:
    spec = creator_spec(
        creator_type=GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR
    )
    assert select_rarefaction_candidate(spec.work_definition)["candidate_id"] == "candidate_b"
    stopped = copy.deepcopy(dict(spec.work_definition))
    stopped["remaining_budgets"] = {"cost": 0}
    assert select_rarefaction_candidate(stopped)["decision"] == "stop"


def test_accepted_gate_requires_enough_unique_evidence() -> None:
    evidence = OpaqueId.mint("evidence", "a")
    gate = EvidenceGate(
        "gate", "gate", 1, "test_result", "host_test", 1, (),
        GateRequirement.REQUIRED, GateAcceptanceState.ACCEPTED, (evidence,),
    )
    record = gate.as_record()
    record["unexpected"] = True
    with pytest.raises(ValueError, match="unknown"):
        EvidenceGate.from_record(record)


def test_plan_result_cannot_change_parent_success_criteria() -> None:
    spec = creator_spec()
    result = {
        "work_graph": {}, "work_packages": [], "worklists": [],
        "cross_cutting_contracts": [], "dependency_and_integration_edges": [],
        "interface_contracts": [], "assumptions": [], "unresolved_questions": [],
        "evidence_gates": [], "template_assignments": [],
        "immutable_success_criteria_refs": ["replacement"],
    }
    with pytest.raises(ValueError, match="cannot alter"):
        validate_template_result(spec, result)
