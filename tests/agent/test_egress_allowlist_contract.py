"""Episode egress allowlists are part of the approved, hashed Architecture.

An ``EpisodeEgressRule`` admits one read-only HTTPS endpoint family. The rule
list rides in ``EpisodeCreationSpec`` (and so in ``spec_hash`` and
``workflow_hash``), round-trips through the model-facing blueprint, and is
bounded by the operator ceiling frozen in ``WorkflowAdmissionAuthority``.
"""
from __future__ import annotations

import pytest

from agent.duet_contracts import DuetIdentity, DuetPolicy, WorkflowAdmissionAuthority
from agent.duet_service import DuetService
from agent.duet_store import DuetStore
from agent.episode_blueprints import (
    EPISODE_CREATION_BLUEPRINT_SCHEMA,
    _CONTINUATION_FUNCTIONS,
    _RAREFACTION_FUNCTIONS,
    creation_blueprint_from_spec,
    creation_spec_from_blueprint,
    workflow_spec_from_blueprint,
)
from agent.episode_contracts import (
    MAX_EGRESS_RESPONSE_BYTES,
    EpisodeContractError,
    EpisodeEgressRule,
    OpaqueId,
    Sha256Digest,
)
from episode_builder._contract_chain import ApprovedBuildRequest


def _rule_record(**overrides) -> dict:
    record = {
        "name": "ragstack_query",
        "host": "www.bv-brc.org",
        "path_prefix": "/ragstack/asm-next/api/",
        "methods": ["GET", "POST"],
        "read_only": True,
        "max_requests": 1500,
        "max_response_bytes": 262144,
        "credential": "patric",
    }
    record.update(overrides)
    return record


def _selection(function, arguments: dict) -> dict:
    return {
        "library": function.library,
        "function_id": function.function_id,
        "interface": function.interface,
        "definition_id": function.definition_id,
        "arguments": arguments,
    }


def _contract(egress: list[dict] | None = None) -> dict:
    return {
        "goal": "Answer every benchmark question against the remote index.",
        "unit": "One query issued and scored.",
        "result": "A scored answer set.",
        "progress": "Count of newly correct answers per unit.",
        "stopping": "Stop when predicted marginal credit falls below the bound.",
        "numeric_control": {
            "rarefaction": _selection(
                _RAREFACTION_FUNCTIONS[0], {"uncertainty_alpha": 0.05}
            ),
            "continuation": _selection(
                _CONTINUATION_FUNCTIONS[0],
                {"max_predicted_marginal_hypervolume": 0.01},
            ),
        },
        "execution_capability_names": [],
        "egress_allowlist": [] if egress is None else egress,
        "deliverable": {
            "kind": "typed_status",
            "description": "Typed terminal status only.",
            "tool_names": [],
        },
    }


def _workflow(*nodes: tuple[str, str | None, list[dict]]) -> dict:
    return {
        "episodes": [
            {
                "local_id": local_id,
                "workflow_parent_local_id": parent,
                "contract": _contract(egress),
            }
            for local_id, parent, egress in nodes
        ]
    }


# --- rule validation -------------------------------------------------------


def test_canonical_rule_record_round_trips_exactly():
    rule = EpisodeEgressRule.from_record(_rule_record())
    assert rule.as_record() == _rule_record()
    assert EpisodeEgressRule.from_record(rule.as_record()) == rule
    assert EpisodeEgressRule.from_record(_rule_record(credential=None)).credential is None


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"name": "Ragstack"}, "name"),
        ({"name": ""}, "name"),
        ({"name": "x" * 65}, "name"),
        ({"host": "WWW.bv-brc.org"}, "host"),
        ({"host": "https://www.bv-brc.org"}, "host"),
        ({"host": "www.bv-brc.org:443"}, "host"),
        ({"host": "www.bv-brc.org/api"}, "host"),
        ({"host": "-bad.example.org"}, "host"),
        ({"host": "a..b"}, "host"),
        ({"host": ""}, "host"),
        ({"path_prefix": "ragstack/"}, "path_prefix"),
        ({"path_prefix": "/a/../b/"}, "path_prefix"),
        ({"path_prefix": "/a/./b"}, "path_prefix"),
        ({"path_prefix": "/a//b"}, "path_prefix"),
        ({"path_prefix": "/a?x=1"}, "path_prefix"),
        ({"path_prefix": "/a#frag"}, "path_prefix"),
        ({"path_prefix": "/a%2e%2e/"}, "path_prefix"),
        ({"path_prefix": "/a b"}, "path_prefix"),
        ({"methods": []}, "methods"),
        ({"methods": ["PUT"]}, "methods"),
        ({"methods": ["DELETE", "GET"]}, "methods"),
        ({"methods": ["get"]}, "methods"),
        ({"methods": ["POST", "GET"]}, "methods"),
        ({"methods": ["GET", "GET"]}, "methods"),
        ({"methods": "GET"}, "methods"),
        ({"read_only": False}, "read_only"),
        ({"read_only": 1}, "read_only"),
        ({"max_requests": 0}, "max_requests"),
        ({"max_requests": True}, "max_requests"),
        ({"max_requests": 1.5}, "max_requests"),
        ({"max_response_bytes": 0}, "max_response_bytes"),
        ({"max_response_bytes": MAX_EGRESS_RESPONSE_BYTES + 1}, "max_response_bytes"),
        ({"credential": "Patric"}, "credential"),
        ({"credential": ""}, "credential"),
    ],
)
def test_every_out_of_contract_rule_is_rejected_at_its_field(overrides, field):
    with pytest.raises(EpisodeContractError) as caught:
        EpisodeEgressRule.from_record(_rule_record(**overrides))
    assert caught.value.field_path == (field,)


def test_rule_record_keys_are_exact():
    extra = _rule_record()
    extra["timeout"] = 5
    missing = _rule_record()
    del missing["credential"]
    for record in (extra, missing):
        with pytest.raises(ValueError, match="malformed Episode egress rule"):
            EpisodeEgressRule.from_record(record)


def test_bounds_are_inclusive():
    assert EpisodeEgressRule.from_record(
        _rule_record(max_requests=1, max_response_bytes=MAX_EGRESS_RESPONSE_BYTES)
    )
    assert EpisodeEgressRule.from_record(_rule_record(path_prefix="/"))
    assert EpisodeEgressRule.from_record(_rule_record(methods=["HEAD"]))


# --- spec and blueprint ----------------------------------------------------


def test_blueprint_and_spec_round_trip_the_allowlist():
    blueprint = _contract([_rule_record(), _rule_record(name="lookup", methods=["GET"])])
    spec = creation_spec_from_blueprint(blueprint)
    assert [rule.name for rule in spec.egress_allowlist] == ["ragstack_query", "lookup"]
    assert creation_blueprint_from_spec(spec) == blueprint
    assert type(spec).from_record(spec.as_record()) == spec


def test_blueprint_schema_requires_the_allowlist_and_describes_it():
    properties = EPISODE_CREATION_BLUEPRINT_SCHEMA["properties"]
    assert "egress_allowlist" in EPISODE_CREATION_BLUEPRINT_SCHEMA["required"]
    allowlist = properties["egress_allowlist"]
    assert allowlist["description"]
    rule_schema = allowlist["items"]
    assert set(rule_schema["required"]) == set(_rule_record())
    assert all(item.get("description") for item in rule_schema["properties"].values())
    blueprint = _contract()
    del blueprint["egress_allowlist"]
    with pytest.raises(ValueError, match="egress_allowlist"):
        creation_spec_from_blueprint(blueprint)


def test_rule_names_are_unique_within_an_episode():
    with pytest.raises(EpisodeContractError) as caught:
        creation_spec_from_blueprint(_contract([_rule_record(), _rule_record()]))
    assert caught.value.field_path == ("egress_allowlist",)


def test_nested_rule_errors_are_anchored_under_the_allowlist():
    with pytest.raises(EpisodeContractError) as caught:
        creation_spec_from_blueprint(_contract([_rule_record(read_only=False)]))
    assert caught.value.field_path == ("egress_allowlist", "read_only")


def test_spec_and_workflow_hashes_cover_the_allowlist():
    without = creation_spec_from_blueprint(_contract())
    with_rule = creation_spec_from_blueprint(_contract([_rule_record()]))
    changed_budget = creation_spec_from_blueprint(
        _contract([_rule_record(max_requests=10)])
    )
    assert len({without.spec_hash, with_rule.spec_hash, changed_budget.spec_hash}) == 3

    plain = workflow_spec_from_blueprint(_workflow(("root", None, [])))
    egress = workflow_spec_from_blueprint(_workflow(("root", None, [_rule_record()])))
    assert plain.workflow_hash != egress.workflow_hash


# --- operator ceiling ------------------------------------------------------


def _authority(**overrides) -> WorkflowAdmissionAuthority:
    values = {
        "duet_id": OpaqueId.mint("duet", "egress-test"),
        "assignable_capability_names": (),
        "egress_hosts": ("www.bv-brc.org", "api.example.org"),
        "egress_credential_names": ("patric",),
    }
    values.update(overrides)
    return WorkflowAdmissionAuthority(**values)


def test_authority_ceiling_is_sorted_hashed_and_round_trips():
    authority = _authority()
    assert authority.egress_hosts == ("api.example.org", "www.bv-brc.org")
    assert WorkflowAdmissionAuthority.from_record(authority.as_record()) == authority
    narrower = _authority(egress_hosts=("www.bv-brc.org",))
    no_credentials = _authority(egress_credential_names=())
    hashes = {authority.content_hash, narrower.content_hash, no_credentials.content_hash}
    assert len(hashes) == 3
    for bad in (
        {"egress_hosts": ("WWW.bv-brc.org",)},
        {"egress_hosts": ("a.org", "a.org")},
        {"egress_credential_names": ("Bad Name",)},
    ):
        with pytest.raises(ValueError):
            _authority(**bad)


def test_authority_reports_which_ceiling_a_rule_exceeds():
    authority = _authority()
    inside = EpisodeEgressRule.from_record(_rule_record())
    outside = EpisodeEgressRule.from_record(
        _rule_record(host="evil.example.org", credential="other")
    )
    assert authority.egress_rule_violations(inside) == ()
    assert authority.egress_rule_violations(outside) == ("host", "credential")


@pytest.fixture
def duet(tmp_path):
    def build(hosts=("www.bv-brc.org",), credentials=("patric",)):
        store = DuetStore(tmp_path / "duet.sqlite3")
        service = DuetService(
            store,
            allowed_episode_capabilities=(),
            allowed_egress_hosts=hosts,
            egress_credential_names=credentials,
        )
        policy = DuetPolicy(policy_id=OpaqueId.mint("policy", "egress"))
        identity = DuetIdentity(
            duet_id=OpaqueId.mint("duet", "egress"),
            human_authority_id=OpaqueId.mint("human", "egress"),
            policy_id=policy.policy_id,
            conversation_id=OpaqueId.mint("conversation", "egress"),
        )
        service.open_duet(identity, policy)
        return service, identity

    return build


def test_default_service_admits_no_egress(tmp_path):
    store = DuetStore(tmp_path / "duet.sqlite3")
    service = DuetService(store, allowed_episode_capabilities=())
    assert service.allowed_egress_hosts == frozenset()
    assert service.egress_credential_names == frozenset()


def test_workflow_within_the_ceiling_has_no_deficits(duet):
    service, identity = duet()
    workflow, deficits = service.validate_duet_workflow(
        identity.duet_id, _workflow(("root", None, [_rule_record()]))
    )
    assert deficits == ()
    assert workflow is not None
    authority = service.workflow_admission_authority(identity.duet_id)
    assert authority.egress_hosts == ("www.bv-brc.org",)
    assert authority.egress_credential_names == ("patric",)
    assert service.duet_status(identity.duet_id)["allowed_egress_hosts"] == [
        "www.bv-brc.org"
    ]


def test_host_outside_the_ceiling_is_a_detailed_deficit(duet):
    service, identity = duet()
    _, deficits = service.validate_duet_workflow(
        identity.duet_id,
        _workflow(
            ("root", None, []),
            ("fetcher", "root", [_rule_record(host="api.example.org")]),
        ),
    )
    (deficit,) = deficits
    assert deficit.code == "egress_host_not_allowed"
    assert deficit.field_path == "egress_allowlist.host"
    assert "fetcher" in deficit.detail and "ragstack_query" in deficit.detail
    assert "api.example.org" in deficit.detail


def test_unknown_credential_is_a_detailed_deficit(duet):
    service, identity = duet(credentials=())
    _, deficits = service.validate_duet_workflow(
        identity.duet_id, _workflow(("root", None, [_rule_record()]))
    )
    (deficit,) = deficits
    assert deficit.code == "egress_credential_unknown"
    assert deficit.field_path == "egress_allowlist.credential"
    assert "root" in deficit.detail and "patric" in deficit.detail


def test_invalid_rule_is_a_detailed_deficit_naming_the_episode(duet):
    service, identity = duet()
    workflow, deficits = service.validate_duet_workflow(
        identity.duet_id,
        _workflow(
            ("root", None, []),
            ("writer", "root", [_rule_record(methods=["DELETE"])]),
        ),
    )
    assert workflow is None
    (deficit,) = deficits
    assert deficit.code == "egress_rule_invalid"
    assert deficit.field_path == "egress_allowlist.methods"
    assert deficit.detail.startswith("writer:")
    assert "DELETE" in deficit.detail


def test_approved_build_request_carries_the_admitted_allowlist(duet):
    service, identity = duet()
    draft = service.record_initial_workflow_draft(
        duet_id=identity.duet_id,
        workflow_blueprint=_workflow(("root", None, [_rule_record()])),
        expected_draft_artifact_id=None,
        expected_draft_hash=None,
        expected_draft_revision=None,
        source_stage="duet",
    )
    authorization = service.approve_current_workflow(
        identity,
        source_draft_artifact_id=OpaqueId(draft["artifact_id"]),
        source_draft_hash=Sha256Digest(draft["content_hash"]),
    )
    request = ApprovedBuildRequest(
        authority_approval=authorization.authority_approval,
        workflow_approval=authorization.workflow_approval,
        frozen_workflow=authorization.frozen_workflow,
        admission_authority=authorization.admission_authority,
        request_nonce="egress-test",
    )
    (root,) = request.frozen_workflow.workflow.episodes
    assert root.contract.egress_allowlist[0].host == "www.bv-brc.org"
    assert request.admission_authority.egress_hosts == ("www.bv-brc.org",)

    # The same frozen authority no longer resolves once the operator narrows the ceiling.
    narrowed = DuetService(
        service.store,
        allowed_episode_capabilities=(),
        allowed_egress_hosts=(),
        egress_credential_names=("patric",),
    )
    with pytest.raises(Exception, match="egress ceiling"):
        narrowed.resolve_current_build_authorization(identity.duet_id)

