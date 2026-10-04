"""Numerical mode over host-admitted observations in the common Run recording.

This projects the existing epistemic journal into controller inputs. It does
not re-run lesson admission, mutate the source Run, or award testing credit.
Other controller observation formats must have an explicit decoder; they may
not be guessed from a worker's prose or replaced with an empty successful trace.
"""

from agent.duet_contracts import canonical_json
from agent.episode_contracts import EpisodeNumericalControlSpec, OpaqueId
from numeric_control_library import CreditObservation

from ..learning import CREDIT_CHANNEL, LearningLedger
from ..learning_baseline import load_learning_baseline
from ..protocol import episode_id_for_path
from .recordings import load_recording
from ..records.experiments import put_record, read_record


def saved_result(artifacts, experiment_id):
    row = read_record(artifacts, "numerical", experiment_id=experiment_id)
    if row is None:
        return None
    value = row["record"]
    from .contracts import ExperimentSpec

    if ExperimentSpec.from_record(value["spec"]).experiment_id != experiment_id:
        raise ValueError("numerical result belongs to another experiment")
    return {
        **value["report"],
        "result_ref": {
            "artifact_id": row["artifact_id"],
            "content_hash": row["content_hash"],
        },
    }


def _local_id(path, plan):
    nodes = {node.local_id: node for node in plan.nodes}
    current = plan.root_local_id
    if not path or path[0]["grain"] != nodes[current].grain_name:
        raise ValueError("recorded invocation does not begin at the admitted root")
    for part in path[1:]:
        children = {
            edge.child_local_id
            for edge in plan.all_edges
            if edge.parent_local_id == current
            and nodes[edge.child_local_id].grain_name == part["grain"]
        }
        if len(children) != 1:
            raise ValueError("recorded invocation has no unique admitted child path")
        current = children.pop()
    return current


def prepare_numerical(spec, *, builds, artifacts, runs):
    """Resolve exact historical scope; no model, Target Workflow code or controller call."""
    request = spec.as_record()
    inputs = builds.inspection_inputs_for_receipt(
        request["build_receipt_ref"]["artifact_id"]
    )
    source, recording = load_recording(
        artifacts,
        runs,
        request["recording_ref"],
        inputs.build_request.frozen_workflow.duet_id.value,
    )
    if (
        source.build_receipt_id != inputs.receipt.receipt_id
        or source.build_request_id != inputs.build_request.build_request_id
        or source.manifest_id != inputs.manifest.manifest_id
    ):
        raise ValueError(
            "numerical replay currently requires the recording's exact admitted build; a changed build requires a separately supported counterfactual projection"
        )
    if request["start"]["artifact_ref"] != request["recording_ref"]:
        raise ValueError(
            "numerical mode must use the same saved recording for start.artifact_ref and recording_ref"
        )
    if request["boundary"]["parent_context_ref"] not in (
        None,
        request["recording_ref"],
    ):
        raise ValueError(
            "numerical parent context comes from the same recorded observations; it cannot be replaced by a different artifact"
        )
    binding = read_record(artifacts, "execution", run_id=source.run_id.value)
    if (
        binding is None
        or binding["record"]["registration"] != source.as_record()
    ):
        raise ValueError("numerical source lacks a verified shared execution binding")
    context = binding["record"].get("context")
    if context is None or context["environment_ref"] != request["environment_ref"]:
        raise ValueError("numerical source environment differs from the experiment")
    if (
        request["launch_ref"] is not None
        and context["model_launch_ref"] != request["launch_ref"]
    ):
        raise ValueError(
            "numerical mode cannot change the recorded external-service configuration"
        )
    scope = request["scope"]
    selected = []
    for invocation in recording["invocations"]:
        path = invocation.get("episode_path")
        if (
            path is None
            or not path
            or path[0]["key"] != source.logical_run_id.value
            or episode_id_for_path(source.logical_run_id, path).value
            != invocation["episode_id"]
        ):
            raise ValueError("numerical source needs exact recorded invocation paths")
        local = _local_id(path, inputs.plan)
        if local not in scope["included_local_ids"]:
            continue
        if scope["kind"] == "episode" and path != scope["invocation_path"]:
            continue
        if (
            scope["kind"] == "nested"
            and path[: len(scope["invocation_path"])] != scope["invocation_path"]
        ):
            continue
        selected.append((invocation, local))
    if not selected:
        raise ValueError("the recording contains no matching invocation for this scope")
    if len({item["episode_id"] for item, _ in selected}) != len(selected):
        raise ValueError("numerical recording repeats an invocation start")
    if scope["kind"] in {"workflow", "refinement"}:
        from .recordings import read_recording

        complete = read_recording(
            runs, source.run_id, through_event_ref=recording["through_event_ref"]
        )
        if recording["selected_episode_ids"] != complete["selected_episode_ids"]:
            raise ValueError(
                "workflow numerical scope requires the complete invocation recording"
            )
    elif not any(
        path["episode_path"] == scope["invocation_path"]
        and local == scope["entry_local_id"]
        for path, local in selected
    ):
        raise ValueError(
            "selected numerical group must include its exact entry invocation"
        )
    contracts = {
        episode.local_id: episode.contract
        for episode in inputs.build_request.frozen_workflow.workflow.episodes
    }
    traces = []
    nodes = {node.local_id: node for node in inputs.plan.nodes}
    for invocation, local in selected:
        contract = contracts[local]
        if nodes[local].interface.startswith("refinement."):
            from .refinement_numerical import prepare_trace

            traces.append(prepare_trace(request=request, source=source, binding=binding, recording=recording, invocation=invocation, local=local, contract=contract, artifacts=artifacts))
            continue
        if contract.epistemic is None:
            raise ValueError(
                f"{local}: no numerical observation decoder for this controller yet; use a supported explicit narrower scope"
            )
        events = [
            row
            for row in recording["learning"]
            if row["episode_id"] == invocation["episode_id"]
        ]
        opened = [row for row in events if row["kind"] == "learning_opened"]
        if len(opened) != 1 or canonical_json(opened[0]["payload"]) != canonical_json({
            "contract": contract.epistemic.as_record(),
            "numerical_control": contract.numeric_control.as_record(),
        }):
            raise ValueError(
                f"{local}: recorded numerical policy differs from its approved contract"
            )
        commits = [row for row in events if row["kind"] == "learning_committed"]
        if not commits:
            raise ValueError(
                f"{local}: no committed numerical observations; an empty trace is not a pass"
            )
        baseline = load_learning_baseline(runs, source, OpaqueId(invocation["episode_id"]))
        traces.append({
            "episode_id": invocation["episode_id"],
            "local_id": local,
            "episode_path": invocation["episode_path"],
            "policy_ref": opened[0]["event_ref"],
            "numeric_control": contract.numeric_control.as_record(),
            "commits": commits,
            **({
                "inherited_history": [{
                    key: row[key] for key in ("unit_id", "baseline_ids", "observation_ids")
                } for row in baseline.history],
                "inherited_history_ref": {
                    key: baseline.reference[key]
                    for key in ("source_registration_ref", "through_event_ref")
                },
            } if baseline is not None else {}),
        })
    return source, recording, traces


def evaluate_numerical(spec, *, builds, artifacts, runs, plan):
    prior = saved_result(artifacts, spec.experiment_id)
    if prior is not None:
        return prior
    source, recording, traces = prepare_numerical(
        spec, builds=builds, artifacts=artifacts, runs=runs
    )
    # Identify the actual host implementation used for this calculation. The
    # recorded worker runtime remains a separate identity; equality of numbers
    # alone does not establish that the two runtime environments were identical.
    from .implementation import host_implementation
    from ..records.experiments import put_data
    from .. import learning
    from . import refinement_numerical
    from iterative_episode_refiner import control

    runtime_ref = put_data(
        artifacts,
        source.duet_id.value,
        "numerical_runtime",
        host_implementation(__file__, learning.__file__, refinement_numerical.__file__, control.__file__),
    )
    results = []
    for trace in traces:
        if trace.get("family") == "refinement":
            units = refinement_numerical.evaluate_trace(trace)
            results.append({key: trace[key] for key in ("episode_id", "local_id", "episode_path", "policy_ref", "numeric_control")} | {"units": units, "family": "refinement"})
            continue
        controller = LearningLedger._controller(
            EpisodeNumericalControlSpec.from_record(trace["numeric_control"])
        )
        inherited = trace.get("inherited_history", ())
        baseline = (
            inherited[0]["baseline_ids"] if inherited
            else trace["commits"][0]["payload"]["baseline_ids"]
        )
        if baseline:
            controller.observe(
                "existing-knowledge",
                CreditObservation.excluded({CREDIT_CHANNEL: baseline}, code="baseline"),
                is_root=True,
            )
        for historical in inherited:
            if canonical_json(historical["baseline_ids"]) != canonical_json(baseline):
                raise ValueError("inherited numerical baseline changes within an invocation")
            controller.observe(
                "recovered",
                CreditObservation.observed({CREDIT_CHANNEL: historical["observation_ids"]}),
                is_root=True,
            )
        units = []
        for committed in trace["commits"]:
            payload = committed["payload"]
            if canonical_json(payload["baseline_ids"]) != canonical_json(baseline):
                raise ValueError(
                    "recorded numerical baseline changes within an invocation"
                )
            step = controller.observe(
                payload["unit_id"],
                CreditObservation.observed({
                    CREDIT_CHANNEL: payload["observation_ids"]
                }),
                is_root=True,
            ).as_record()
            units.append({
                "unit_id": payload["unit_id"],
                "source_event_ref": committed["event_ref"],
                "recorded": payload["numeric_step"],
                "recomputed": step,
                "matches": canonical_json(step)
                == canonical_json(payload["numeric_step"]),
                "source_terminal_state": payload["terminal_state"],
            })
        results.append(
            {
                key: trace[key]
                for key in (
                    "episode_id",
                    "local_id",
                    "episode_path",
                    "policy_ref",
                    "numeric_control",
                )
            }
            | {"units": units, "reused_unit_count": len(inherited)}
            | ({"inherited_history_ref": trace["inherited_history_ref"]} if inherited else {})
        )
    report = {
        "experiment_id": spec.experiment_id,
        "execution_status": "evaluated",
        "mode": "numerical",
        "candidate_ref": spec.as_record()["candidate_ref"],
        "candidate_verdict": "unmeasured",
        "scope": plan["scope"],
        "recording_ref": spec.as_record()["recording_ref"],
        "source_run_id": source.run_id.value,
        "source_terminal_status": recording["source_terminal_status"],
        "source_runtime_identity": source.runtime_identity.as_record(),
        "numerical_runtime_ref": runtime_ref,
        "unobserved_local_ids": sorted(
            set(spec.as_record()["scope"]["included_local_ids"])
            - {row["local_id"] for row in traces}
        ),
        "controller_comparison": "reproduced"
        if all(unit["matches"] for row in results for unit in row["units"])
        else "different",
        "invocations": results,
        "requirements": spec.as_record()["requirements"],
        "unresolved_questions": spec.as_record()["unresolved_questions"],
        "progress": {
            "admitted": False,
            "reason": "Reused observations are not new task evidence or a new learning admission.",
        },
        "limitations": [
            "Only registered host numerical functions were evaluated; candidate acquisition, editing, model/HTTP calls and confinement were not exercised.",
            "The entire selected observed history is compared, including observations after a changed stop decision; this is not an executable counterfactual trajectory.",
            "Candidate acceptance and measurement adequacy remain separate; reproduced decisions do not establish either.",
            "This is a new numerical experiment over an immutable prefix, not continuation of the source Run or restoration of nested state.",
        ],
    }
    value = {"spec": spec.as_record(), "plan": plan, "report": report}
    put_record(
        artifacts, "numerical", experiment_id=spec.experiment_id,
        duet_id=plan.get("subject", {}).get("owner_duet_id", source.duet_id.value),
        record=value,
    )
    return saved_result(artifacts, spec.experiment_id)
