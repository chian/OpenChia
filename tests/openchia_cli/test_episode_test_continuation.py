"""CLI continuation uses the common service and immutable exact Run evidence.

Build/launch approval, profile config, HTTP broker, stores and host reauthorization
are real. The executor publishes supplied results and HTTP transport is supplied;
this does not prove worker reconstruction or confinement. No target/model is contacted.
"""

import asyncio
import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import EpisodeCreationSpec, EpisodeEgressRule, OpaqueId, Sha256Digest
from agent.episode_launch import resolve_launch
from agent import secret_scope
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from function_library.epistemic_contract import inquiry_contract
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunTerminalStatus
from episode_runtime.records.experiments import put_data, read_record
from episode_runtime.testing_harness.contracts import ExperimentSpec
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from llm_call_library import CallOptions
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from openchia_cli.config import atomic_config_write
from openchia_cli.episode_test_command import _http_credentials, main
from tests.episode_runtime.conftest import claim_store, numerical_control
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request, _module_response, _plan_response,
)
from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing_harness.test_experiment_planning import experiment
from tests.episode_runtime.testing_harness.test_measurements import ResultOnlyExecutor


class SuppliedContinuationExecutor(ResultOnlyExecutor):
    def __init__(self, root, identity, http_request):
        super().__init__(root, identity)
        self.http_request = http_request

    async def execute(self, **arguments):
        if arguments["registration"].resume_from is not None:
            self.authority = await arguments["continuation_admission"]()
        response = await arguments["http_broker"](
            local_id="inquiry", request=self.http_request
        )
        self.result = {"http_result": response}
        return await super().execute(**arguments)


async def _profile_command(home, arguments, capsys, secrets):
    previous_multiplex = secret_scope.is_multiplex_active()
    secret_scope.set_multiplex_active(True)
    home_token = set_hermes_home_override(home)
    secret_token = secret_scope.set_secret_scope({}, profile_home=str(home))
    try:
        code = await asyncio.to_thread(main, arguments)
    finally:
        secret_scope.reset_secret_scope(secret_token)
        reset_hermes_home_override(home_token)
        secret_scope.set_multiplex_active(previous_multiplex)
    output = capsys.readouterr().out
    assert all(secret not in output for secret in secrets)
    return code, json.loads(output)


@pytest.mark.asyncio
async def test_continue_cli_preserves_exact_evidence_and_reuses_shared_dispatch(
    tmp_path, monkeypatch, capsys
):
    rule = EpisodeEgressRule(
        name="fixture_query", host="api.example.org", path_prefix="/query/",
        methods=("GET",), read_only=True, max_requests=3,
        max_response_bytes=4096, credential="fixture_access",
    )
    request = _approved_request(
        tmp_path,
        allowed_egress_hosts=(rule.host,), egress_credential_names=(rule.credential,),
        spec=EpisodeCreationSpec(
            goal="Read the approved endpoint and preserve its evidence.",
            progress="Host-admitted observations", stopping="Registered continuation",
            numeric_control=numerical_control(0.1), egress_allowlist=(rule,),
            epistemic=inquiry_contract(
                goal_class="query", domain="fixture", environment={"fixture": "cli-http"},
            ),
        ),
    )
    builds = BuildStore(tmp_path)

    async def builder_model(call):
        prompt = json.loads(call.messages[-1]["content"])
        response = _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(builder_model):
        receipt = await EpisodeBuilder(
            store=builds, planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    identity = claim_store(tmp_path / "identity")[1].runtime_identity
    executor = SuppliedContinuationExecutor(tmp_path / "execution", identity, {
        "method": "GET", "url": "https://api.example.org/query/item",
        "headers": {}, "body": None, "timeout": None,
    })
    executor.terminal = RunTerminalStatus.INTERRUPTED
    homes = [tmp_path / "profile-a", tmp_path / "profile-b"]
    tokens = ["fixture-token-alpha", "fixture-token-beta"]
    for home, token in zip(homes, tokens, strict=True):
        home.mkdir()
        token_file = home / "access.token"
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(0o600)
        atomic_config_write(home / "config.yaml", {"openchia": {"egress": {
            "allowed_hosts": [rule.host],
            "credentials": {rule.credential: {"path": str(token_file)}},
        }}})
    outgoing_headers = []

    async def supplied_http(_transport, **arguments):
        outgoing_headers.append(dict(arguments["headers"]))
        return 200, {"content-type": "application/json"}, b'{"value":"observed"}'

    monkeypatch.setattr("episode_runtime.http_broker.HttpxHostTransport.__call__", supplied_http)
    launch = resolve_launch({
        "project": "continuation-cli-fixture",
        "project_root": str(tmp_path),
        "env_files": [],
        "routes": {
            "target": {
                "provider": "custom",
                "model": "unused-supplied-target",
                "base_url": "http://localhost:9999/v1",
                "api_mode": "chat_completions",
                "auth": {"kind": "none"},
            }
        },
        "model_slots": {"selector": "target", "executor": "target"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    database = tmp_path / "duet.db"
    with DuetStore(database) as artifacts:
        owner = request.frozen_workflow.duet_id.value
        FixtureLaunchHost(artifacts, builds, owner).approve_fixture(launch)
        raw = experiment(artifacts, request, receipt)
        raw["launch_ref"] = put_data(artifacts, owner, "launch", launch.record)
        spec = ExperimentSpec.from_record(raw)

    factories = []

    def executor_factory(**options):
        factories.append(options)

        def bind(runs):
            assert runs.root == executor.run_store.root
            executor.run_store = runs
            return executor

        return bind

    monkeypatch.setattr(
        "episode_runtime.executor_selection.make_run_executor_factory", executor_factory
    )
    spec_file = tmp_path / "experiment.json"
    spec_file.write_text(json.dumps(raw), encoding="utf-8")
    run_arguments = [
        "run", "--spec", str(spec_file), "--duet-store", str(database),
        "--build-store", str(tmp_path), "--run-store", str(executor.run_store.root),
    ]
    code, first = await _profile_command(homes[0], run_arguments, capsys, tokens)
    assert code == 2 and first["execution_status"] == "interrupted", first
    assert executor.result["http_result"]["outcome"] == "ok"
    reference = InterruptedRunRef.from_run(executor.run_store, first["run_id"])
    assert first["resume_from"] == reference.as_record()
    original_audit = executor.run_store.read_audit_log(reference.run_id)
    with DuetStore(database) as artifacts:
        original_dispatch = read_record(artifacts, "dispatch", experiment_id=spec.experiment_id)
    resume_file = tmp_path / "interruption.json"
    arguments = [
        "continue",
        "--experiment-id",
        spec.experiment_id,
        "--resume-from",
        str(resume_file),
        "--duet-store",
        str(database),
        "--build-store",
        str(tmp_path),
        "--run-store",
        str(executor.run_store.root),
    ]
    forged = {
        **reference.as_record(),
        "terminal_event_hash": Sha256Digest.of_bytes(b"not the final event").value,
    }
    resume_file.write_text(json.dumps(forged), encoding="utf-8")
    code, rejected = await _profile_command(homes[1], arguments, capsys, tokens)
    assert code == 2
    assert "exact final interruption" in rejected["detail"]
    assert executor.calls == 1

    resume_file.write_text(json.dumps(reference.as_record()), encoding="utf-8")
    executor.terminal = RunTerminalStatus.SUCCEEDED
    code, continued = await _profile_command(homes[1], arguments, capsys, tokens)
    assert code == 0
    assert executor.result["http_result"]["outcome"] == "ok"
    assert continued["logical_run_id"] == first["run_id"]
    assert continued["run_id"] != first["run_id"]
    assert continued["experiment_id"] == spec.experiment_id
    assert continued["execution_status"] == "succeeded"
    assert not continued["progress"]["admitted"]
    assert (
        executor.authority["launch_approval_ref"]["configuration_hash"]
        == launch.configuration_hash
    )
    assert executor.calls == 2
    code, repeated = await _profile_command(homes[1], arguments, capsys, tokens)
    assert code == 0 and repeated == continued
    assert executor.calls == 2
    assert executor.run_store.read_audit_log(reference.run_id) == original_audit
    with DuetStore(database) as artifacts:
        assert (
            read_record(artifacts, "dispatch", experiment_id=spec.experiment_id)
            == original_dispatch
        )
    raw["question"] = "Does the same approved endpoint answer a new experiment?"
    spec_file.write_text(json.dumps(raw), encoding="utf-8")
    code, another = await _profile_command(homes[0], run_arguments, capsys, tokens)
    assert code == 0 and another["execution_status"] == "succeeded", another
    assert executor.result["http_result"]["outcome"] == "ok"
    assert executor.calls == 3
    assert [headers["authorization"] for headers in outgoing_headers] == [
        f"Bearer {tokens[0]}", f"Bearer {tokens[1]}", f"Bearer {tokens[0]}",
    ]
    for run_id in (first["run_id"], continued["run_id"], another["run_id"]):
        evidence = executor.run_store.read_evidence(OpaqueId(run_id))
        audit = executor.run_store.read_audit_log(OpaqueId(run_id))
        serialized = json.dumps({
            "evidence": evidence.as_record(), "audit": [event.as_record() for event in audit],
        })
        assert all(token not in serialized for token in tokens)
    assert all(
        options["backend"] == "auto" and options["image"] is None
        for options in factories
    )

    assert main(["describe"]) == 0
    description = json.loads(capsys.readouterr().out)
    assert "continue" in description["available_operations"]
    payload = description["worker_payload_schemas"]["continue"]["oneOf"][0]
    assert set(payload["required"]) == {"experiment_id", "resume_from"}
    assert set(payload["properties"]["resume_from"]["required"]) == set(
        reference.as_record()
    )
    assert payload["properties"]["resume_from"]["additionalProperties"] is False


def test_nonlive_modes_do_not_require_valid_live_egress_configuration(tmp_path):
    atomic_config_write(tmp_path / "config.yaml", {"openchia": {"egress": {
        "credentials": {"fixture_access": {"path": "not-an-absolute-token-path"}},
    }}})
    home_token = set_hermes_home_override(tmp_path)
    try:
        assert _http_credentials("recorded") == {}
        assert _http_credentials("numerical") == {}
        for mode in ("live_fresh", "live_saved"):
            with pytest.raises(ValueError, match="must be absolute"):
                _http_credentials(mode)
    finally:
        reset_hermes_home_override(home_token)
