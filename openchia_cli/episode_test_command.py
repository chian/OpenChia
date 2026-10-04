"""Structured CLI for the shared Episode experiment service, without chat startup."""

import argparse
import asyncio
import json
from pathlib import Path

from agent.duet_contracts import canonical_json
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.schema import vocabulary
from .episode_launch_setup import setup_launch


def _describe(_args):
    return {
        **vocabulary(),
        "available_operations": list(_OPERATIONS),
        "implementation_status": "Shared execution, scoped replay, numerical comparison, frozen measurements, campaign evaluations and Duet-bound refinement jobs are connected. continue requests exact interrupted-execution reconstruction through the same executor, subject to source support and current authority. Additional typed component adapters and arbitrary later-unit starts remain unsupported; native and live acceptance are separate verification claims.",
    }


def _spec(args):
    return ExperimentSpec(Path(args.spec).read_text(encoding="utf-8-sig"))


def _validate(args):
    spec = _spec(args)
    return {
        "valid": True,
        "experiment_id": spec.experiment_id,
        "content_hash": spec.content_hash,
        "execution_authorized": False,
    }


def _preview(args):
    from agent.duet_store import DuetStore
    from episode_builder.store import BuildStore
    from episode_runtime.testing.planning import preview_experiment
    from episode_runtime.store import RunStore

    duet_path = Path(args.duet_store).expanduser()
    build_path = Path(args.build_store).expanduser()
    if not duet_path.is_file() or not build_path.is_dir():
        raise ValueError(
            "preview requires an existing Duet database and BuildStore directory"
        )
    with DuetStore(duet_path) as artifacts:
        return preview_experiment(
            _spec(args),
            builds=BuildStore(build_path),
            artifacts=artifacts,
            runs=None
            if args.run_store is None or not Path(args.run_store).expanduser().is_dir()
            else RunStore(args.run_store),
        )


def _recording(args):
    from episode_runtime.store import RunStore
    from episode_runtime.testing.recordings import read_recording, recording_summary

    root = Path(args.run_store).expanduser()
    if not root.is_dir():
        raise ValueError("recording inspection requires an existing RunStore")
    value = read_recording(RunStore(root), args.run_id, episode_ids=args.episode_id)
    result = value if args.include_content else recording_summary(value)
    if args.save:
        from agent.duet_store import DuetStore
        from episode_runtime.testing.recordings import save_recording

        if args.duet_store is None or not Path(args.duet_store).expanduser().is_file():
            raise ValueError(
                "--save requires --duet-store naming the source Run's existing Duet database"
            )
        with DuetStore(args.duet_store) as artifacts:
            result["recording_ref"] = save_recording(
                artifacts,
                RunStore(root),
                args.run_id,
                episode_ids=args.episode_id,
                through_event_ref=value["through_event_ref"],
            )
    return result


def _register_launch(args):
    from agent.duet_store import DuetStore
    from agent.episode_launch import read_launch_spec, resolve_launch
    from agent.episode_launch_host import resolve_approved_launch
    from episode_runtime.records.experiments import put_data

    launch = resolve_launch(read_launch_spec(args.file))
    with DuetStore(args.duet_store) as artifacts:
        if artifacts.get_duet(args.duet_id) is None:
            raise ValueError("register-launch requires an existing owning Duet")
        _, launch, approval_ref = resolve_approved_launch(
            artifacts, args.duet_id, configuration_hash=launch.configuration_hash
        )
        reference = put_data(artifacts, args.duet_id, "launch", launch.record)
    return {
        "launch_ref": reference,
        "configuration_hash": launch.configuration_hash,
        "approval_ref": approval_ref,
        "credential_values_stored": False,
    }


def _boundary(args):
    from agent.duet_store import DuetStore
    from episode_runtime.store import RunStore
    from episode_runtime.testing.boundaries import capture_boundary
    from episode_runtime.testing.units import capture_unit_boundary

    if not Path(args.duet_store).is_file() or not Path(args.run_store).is_dir():
        raise ValueError("boundary capture requires existing source stores")
    with DuetStore(args.duet_store) as artifacts:
        capture = capture_unit_boundary if args.unit_id is not None else capture_boundary
        return capture(
            artifacts, RunStore(args.run_store), args.run_id,
            args.unit_id if args.unit_id is not None else args.episode_id,
        )


def _register_measure(args):
    from agent.duet_store import DuetStore
    from episode_builder.store import BuildStore
    from episode_runtime.testing.criteria import register_criterion

    with DuetStore(args.duet_store) as artifacts:
        return register_criterion(
            json.loads(Path(args.file).read_text(encoding="utf-8-sig")),
            artifacts=artifacts,
            builds=BuildStore(args.build_store),
            duet_id=args.duet_id,
        )


def _http_credentials(mode):
    if mode not in {"live_fresh", "live_saved"}:
        return {}
    from episode_runtime.http_broker import load_egress_config
    from .config import load_config_readonly

    return load_egress_config(load_config_readonly())[1]


def _run(args):
    from agent.duet_store import DuetStore
    from episode_builder.store import BuildStore
    from episode_runtime.executor_selection import make_run_executor_factory
    from episode_runtime.store import RunStore
    from episode_runtime.testing.service import ExperimentService

    plan = _preview(args)
    if not plan["resolved"]:
        return {
            "experiment_id": plan["experiment_id"],
            "execution_status": "unavailable",
            "candidate_verdict": "unmeasured",
            "plan": plan,
        }
    spec = _spec(args)
    mode = spec.as_record()["mode"]
    credentials = _http_credentials(mode)
    runs = RunStore(args.run_store)
    executor = (
        None
        if mode == "numerical"
        else make_run_executor_factory(
            repository_root=Path(__file__).resolve().parents[1],
            backend=args.backend,
            image=args.image,
        )(runs)
    )
    with DuetStore(args.duet_store) as artifacts:
        service = ExperimentService(
            artifacts=artifacts,
            builds=BuildStore(args.build_store),
            runs=runs,
            executor=executor,
            http_credentials=credentials,
        )
        return asyncio.run(service.run(spec))


def _status(args):
    from agent.duet_store import DuetStore
    from episode_runtime.store import RunStore
    from episode_runtime.testing.service import ExperimentService
    from episode_runtime.testing.execution import RunExecution

    with DuetStore(args.duet_store) as artifacts:
        if args.run_id:
            return RunExecution.status(artifacts, RunStore(args.run_store), args.run_id)
        return ExperimentService.status(
            artifacts, RunStore(args.run_store), args.experiment_id
        )


def _continue(args):
    from agent.duet_store import DuetStore
    from episode_builder.store import BuildStore
    from episode_runtime.continuation import InterruptedRunRef
    from episode_runtime.executor_selection import make_run_executor_factory
    from episode_runtime.store import RunStore
    from episode_runtime.records.experiments import read_record
    from episode_runtime.testing.service import ExperimentService

    reference = InterruptedRunRef.from_record(
        json.loads(Path(args.resume_from).read_text(encoding="utf-8-sig"))
    )
    if not Path(args.duet_store).expanduser().is_file() or any(
        not Path(path).expanduser().is_dir()
        for path in (args.build_store, args.run_store)
    ):
        raise ValueError("continuation requires the experiment's existing Duet, BuildStore and RunStore")
    runs = RunStore(args.run_store)
    executor = make_run_executor_factory(
        repository_root=Path(__file__).resolve().parents[1],
        backend=args.backend, image=args.image,
    )(runs)
    with DuetStore(args.duet_store) as artifacts:
        dispatch = read_record(artifacts, "dispatch", experiment_id=args.experiment_id)
        credentials = _http_credentials(
            None if dispatch is None else dispatch["record"]["spec"]["mode"]
        )
        service = ExperimentService(
            artifacts=artifacts, builds=BuildStore(args.build_store),
            runs=runs, executor=executor, http_credentials=credentials,
        )
        return asyncio.run(service.continue_run(
            experiment_id=args.experiment_id, resume_from=reference.as_record(),
        ))


def _history(args):
    from agent.duet_store import DuetStore
    from episode_runtime.store import RunStore
    from episode_runtime.testing.service import ExperimentService

    query = {key: getattr(args, key) for key in (
        "kind", "limit", "after", "experiment_id", "run_id",
        "campaign_id", "invocation_id", "refinement_collection",
    ) if getattr(args, key) is not None}
    if args.query is not None:
        if query:
            raise ValueError("use --query or individual history flags, not both")
        query = json.loads(Path(args.query).read_text(encoding="utf-8-sig"))
    with DuetStore(args.duet_store) as artifacts:
        return ExperimentService.history(
            artifacts, RunStore(args.run_store), duet_id=args.duet_id,
            query=query,
        )


def _run_record(args):
    from agent.episode_contracts import OpaqueId
    from episode_runtime.store import RunStore

    runs = RunStore(args.run_store)
    return (
        runs.refresh_run_record(OpaqueId(args.run_id)) if args.refresh
        else runs.read_run_record(OpaqueId(args.run_id))
    )


def _inventory(args):
    from agent.duet_store import DuetStore
    from agent.episode_contracts import OpaqueId
    from episode_runtime.store import RunStore
    from episode_runtime.testing.service import ExperimentService

    runs = RunStore(args.run_store)
    query = {key: getattr(args, key) for key in ("kind", "episode_id", "after", "limit") if getattr(args, key) is not None}
    if args.through_event_ref is not None:
        query["through_event_ref"] = json.loads(args.through_event_ref)
    if args.query is not None:
        if query:
            raise ValueError("use --query or individual query flags, not both")
        query = json.loads(Path(args.query).read_text(encoding="utf-8-sig"))
    if args.run_id is not None:
        owner = runs.read_registration(OpaqueId(args.run_id)).duet_id.value
        return ExperimentService.inventory(
            None, runs, duet_id=owner, source={"kind": "run", "run_id": args.run_id}, query=query,
        )
    if args.duet_store is None or args.duet_id is None:
        raise ValueError("experiment/recording inventory requires --duet-store and --duet-id")
    with DuetStore(args.duet_store) as artifacts:
        source = {"kind": "experiment", "experiment_id": args.experiment_id}
        if args.recording_id is not None:
            row = artifacts.get_artifact(args.recording_id)
            if row is None or row["duet_id"] != args.duet_id:
                raise ValueError("recording is unavailable to the selected owner")
            source = {"kind": "recording", "recording_ref": {
                key: row[key] for key in ("artifact_id", "content_hash")
            }}
        return ExperimentService.inventory(artifacts, runs, duet_id=args.duet_id, source=source, query=query)


def _compare(args):
    from agent.duet_store import DuetStore
    from episode_runtime.testing.comparison import compare_experiments

    with DuetStore(args.duet_store) as artifacts:
        return compare_experiments(artifacts, args.before, args.after)


_OPERATIONS = {
    "describe": _describe,
    "history": _history,
    "run-record": _run_record,
    "inventory": _inventory,
    "validate": _validate,
    "preview": _preview,
    "recording": _recording,
    "boundary": _boundary,
    "register-launch": _register_launch,
    "register-measure": _register_measure,
    "setup-launch": setup_launch,
    "run": _run,
    "continue": _continue,
    "status": _status,
    "results": _status,
    "compare": _compare,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="openchia test",
        description="Design and inspect Episode experiments using the shared testing service.",
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser(
        "describe",
        help="Print the request schema, scope/mode vocabulary and available operations",
    )
    history = commands.add_parser(
        "history", help="List experiments or shared ordinary/refinement executions without scanning Run audits"
    )
    for name in ("duet-store", "duet-id", "run-store"):
        history.add_argument(f"--{name}", required=True)
    history.add_argument("--limit", type=int)
    history.add_argument("--kind", choices=("experiments", "executions", "refinement"))
    history.add_argument("--query", help="HistoryQuery JSON file; pass a returned next_query unchanged")
    history.add_argument("--campaign-id", help="With --kind refinement, select an existing campaign")
    history.add_argument("--invocation-id", help="Refinement assignment whose requirement scope limits this history")
    history.add_argument("--refinement-collection", choices=("observations", "reports", "conflicts", "controls"))
    history.add_argument("--after", help="next_cursor from the previous history page")
    history_source = history.add_mutually_exclusive_group()
    history_source.add_argument("--experiment-id", help="List this experiment's saved recordings instead of experiments")
    history_source.add_argument("--run-id", help="With --kind executions, list this Run's saved recordings")
    record = commands.add_parser(
        "run-record", help="Inspect compact maintained Run facts; no audit reconstruction by default"
    )
    for name in ("run-store", "run-id"):
        record.add_argument(f"--{name}", required=True)
    record.add_argument(
        "--refresh", action="store_true",
        help="Explicitly verify audit and rebuild this derived view; never executes or resumes a Run",
    )
    inventory = commands.add_parser("inventory", help="Browse indexed invocation/unit facts, without decoding Run audit bodies")
    inventory.add_argument("--run-store", required=True)
    source = inventory.add_mutually_exclusive_group(required=True)
    for name in ("run-id", "experiment-id", "recording-id"):
        source.add_argument(f"--{name}")
    for name in ("duet-store", "duet-id", "episode-id"):
        inventory.add_argument(f"--{name}")
    inventory.add_argument("--kind", choices=("invocations", "units"))
    inventory.add_argument("--after", type=int, help="Event sequence cursor from next_query")
    inventory.add_argument("--limit", type=int)
    inventory.add_argument("--through-event-ref", help="Exact audit-prefix reference as JSON")
    inventory.add_argument("--query", help="InventoryQuery JSON file, such as a returned next_query")
    validate = commands.add_parser(
        "validate", help="Validate experimental intent without executing anything"
    )
    validate.add_argument("--spec", required=True, help="Experiment JSON file")
    preview = commands.add_parser(
        "preview", help="Resolve exact candidate scope and report missing context"
    )
    preview.add_argument("--spec", required=True, help="Experiment JSON file")
    preview.add_argument(
        "--duet-store", required=True, help="Existing Duet SQLite database"
    )
    preview.add_argument(
        "--build-store", required=True, help="Existing BuildStore root"
    )
    preview.add_argument(
        "--run-store",
        help="Existing RunStore, required to resolve numerical recordings",
    )
    recording = commands.add_parser(
        "recording", help="Inspect committed Run exchanges and recording gaps"
    )
    recording.add_argument("--run-store", required=True, help="Existing RunStore root")
    recording.add_argument("--run-id", required=True, help="Exact source Run ID")
    recording.add_argument(
        "--save",
        action="store_true",
        help="Save an immutable journal selector for recording_ref; does not copy or rewrite the audit",
    )
    recording.add_argument(
        "--duet-store", help="Existing source Duet database, required with --save"
    )
    recording.add_argument(
        "--episode-id",
        action="append",
        help="Select an exact invocation; repeat for a group (default: entire Run)",
    )
    recording.add_argument(
        "--include-content",
        action="store_true",
        help="Include typed request/response and unit data; default is metadata only",
    )
    boundary = commands.add_parser("boundary", help="Save an exact invocation or unit boundary from the common Run journal")
    for name in ("run-store", "run-id", "duet-store"):
        boundary.add_argument(f"--{name}", required=True)
    selection = boundary.add_mutually_exclusive_group(required=True)
    selection.add_argument("--episode-id", help="Exact invocation from test inventory")
    selection.add_argument("--unit-id", help="Exact unit from test inventory; capture ends at that unit")
    register = commands.add_parser(
        "register-launch",
        help="Register this Duet's exact human-approved launch; store only public settings and credential references",
    )
    register.add_argument("--file", required=True, help="Existing /launch JSON file")
    register.add_argument("--duet-store", required=True)
    register.add_argument("--duet-id", required=True)
    measure = commands.add_parser(
        "register-measure",
        help="Freeze an experimental criterion and validate its satisfactory/violating controls; grants no execution or parent-acceptance authority",
    )
    for name in ("file", "duet-store", "duet-id", "build-store"):
        measure.add_argument(f"--{name}", required=True)
    setup = commands.add_parser(
        "setup-launch",
        help="Select function model slots and endpoints; save an ordinary /launch file and private credentials without approving or activating it",
    )
    setup.add_argument(
        "--directory",
        required=True,
        help="New private output directory (existing directories are not overwritten)",
    )
    setup.add_argument(
        "--from",
        dest="source",
        help="Existing launch JSON instead of the interactive route/role wizard",
    )
    setup.add_argument(
        "--prompt-credentials",
        action="store_true",
        help="Prompt without echo for the named API keys; never pass key values in arguments",
    )
    run = commands.add_parser(
        "run",
        help="Dispatch a supported experiment through the existing confined runtime (execution is not acceptance)",
    )
    for name in ("spec", "duet-store", "build-store", "run-store"):
        run.add_argument(f"--{name}", required=True)
    run.add_argument(
        "--backend", choices=("auto", "systemd", "container"), default="auto"
    )
    run.add_argument(
        "--image", help="Explicit existing container image for the container backend"
    )
    continuation = commands.add_parser(
        "continue",
        help="Reconstruct the exact interrupted experiment before permitting new work; does not restart or change its scope",
        description="Continue an interrupted target or declared checker through the shared executor. Requires exact final interruption evidence and current approval. Refiner jobs require their owning Duet-bound host service; this plain CLI does not supply or substitute that model binding.",
    )
    for name in ("experiment-id", "duet-store", "build-store", "run-store"):
        continuation.add_argument(f"--{name}", required=True)
    continuation.add_argument(
        "--resume-from", required=True,
        help="JSON file containing the exact resume_from object from status: run_id, registration_hash, terminal_event_id and terminal_event_hash",
    )
    continuation.add_argument(
        "--backend", choices=("auto", "systemd", "container"), default="auto"
    )
    continuation.add_argument("--image", help="Explicit existing image for the container backend")
    status = commands.add_parser(
        "status",
        aliases=["results"],
        help="Inspect durable experiment status without launching or contacting a model",
    )
    identity = status.add_mutually_exclusive_group(required=True)
    identity.add_argument("--experiment-id", help="Experiment specification identity")
    identity.add_argument(
        "--run-id",
        help="Shared execution identity, including refiner target/checker/control Runs",
    )
    for name in ("duet-store", "run-store"):
        status.add_argument(f"--{name}", required=True)
    comparison = commands.add_parser(
        "compare",
        help="Compare frozen requirement outcomes; report incompatible contexts without claiming regression or repair",
    )
    for name in ("duet-store", "before", "after"):
        comparison.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    try:
        result = _OPERATIONS[args.operation](args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(canonical_json({"error": type(exc).__name__, "detail": str(exc)}))
        return 2
    print(
        json.dumps(
            result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        )
    )
    unavailable = not result.get("resolved", True) or result.get(
        "execution_status"
    ) in {
        "unavailable",
        "failed",
        "invalid",
        "blocked",
        "interrupted",
        "cancelled",
        "resource_limited",
    }
    return (
        2
        if unavailable
        or result.get("candidate_verdict") == "fail"
        or result.get("comparison_status") == "unavailable"
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
