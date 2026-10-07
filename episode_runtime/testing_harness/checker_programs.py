"""Execute an immutable checking program against explicit, read-only inputs.

The selected Run backend supplies process confinement and cancellation. This is
a checking instrument, not a Target Workflow Run: its receipt records the exact
program, fixture/candidate, environment and process outcome, without inventing
Run events or treating a coding assistant's diagnostic output as evidence.
"""

from collections.abc import Mapping
import json
from pathlib import Path, PurePosixPath
import tempfile

from agent.duet_contracts import canonical_json
from episode_runtime.records.experiments import put_data, read_reference


def source_files(value):
    if not isinstance(value, Mapping):
        raise ValueError("checking sources must be a path-to-text object")
    for name, text in value.items():
        if not isinstance(name, str):
            raise ValueError("checking source paths must be text")
        path = PurePosixPath(name)
        if (not name or path.is_absolute()
                or path.as_posix() != name or any(part in {".", ".."} for part in path.parts)
                or "\\" in name or "\x00" in name or not isinstance(text, str)):
            raise ValueError("checking sources require relative ordinary file paths and text")
        if any(parent.as_posix() in value for parent in path.parents):
            raise ValueError("a checking file cannot also be a directory")
    return value


def validate_program(program):
    if not isinstance(program, Mapping) or set(program) != {"files", "entrypoint"}:
        raise ValueError("checking program requires files and entrypoint")
    files = source_files(program["files"])
    entry = program["entrypoint"]
    if not isinstance(entry, str) or entry.count(":") != 1:
        raise ValueError("checking entrypoint must be module:function")
    module, function = entry.split(":")
    if (not function.isidentifier() or not all(part.isidentifier() for part in module.split("."))
            or module.replace(".", "/") + ".py" not in files):
        raise ValueError("checking entrypoint must resolve to its supplied Python source")
    for path, text in files.items():
        if path.endswith(".py"):
            try:
                compile(text, path, "exec")  # Parse only; generated code never runs in this host.
            except SyntaxError as exc:
                raise ValueError(f"checking source {path} does not compile: {exc}") from exc
    return program


def validate_fixture(fixture):
    if not isinstance(fixture, Mapping) or set(fixture) != {"files", "materialization", "input"}:
        raise ValueError("checker fixture requires files, materialization and input")
    source_files(fixture["files"])
    if not isinstance(fixture["materialization"], Mapping):
        raise ValueError("checker fixture materialization must be an object")
    canonical_json(fixture)
    return fixture


# Runs only inside the existing isolated backend. The input tree is mounted
# read-only; only scratch is writable. No profile, credential store or checkout
# is supplied. The authored function receives no expected verdict or polarity.
_RUNNER = r'''
import contextlib, importlib, io, json, pathlib, sys, traceback
root = pathlib.Path(sys.argv[1])
runtime, dependencies = sys.argv[2:4]
sys.dont_write_bytecode = True
sys.path[:0] = [str(root / "program"), str(root / "target"), runtime]
if dependencies:
    sys.path.append(dependencies)
request = json.loads((root / "request.json").read_text(encoding="utf-8"))
logs = io.StringIO()
try:
    with contextlib.redirect_stdout(logs):
        module, function = request["entrypoint"].split(":")
        measure = getattr(importlib.import_module(module), function)
        result = measure({"source_root": str(root / "target"),
                          "materialization": request["materialization"],
                          "input": request["input"]})
        encoded = json.dumps({"status": "completed", "result": result}, allow_nan=False)
except BaseException:
    encoded = json.dumps({"status": "error", "error": traceback.format_exc()})
sys.stderr.write(logs.getvalue())
sys.stdout.write(encoded)
'''


async def execute_program(*, executor, artifacts, builds, runs, duet_id, program,
                          fixture, subject, environment_service, preparation=None):
    """Return saved process evidence; callers own review, control and credit rules."""
    validate_program(program)
    validate_fixture(fixture)
    if executor.run_store is not runs:
        raise ValueError("checking must use the selected RunStore and executor")
    runtime = environment_service.runtime_identity
    intent = {
        "program": program, "fixture": fixture, "subject": subject,
        "runtime": runtime.as_record(),
        "runner_source_hash": builds.put_blob(_RUNNER.encode("utf-8")).value,
        "environment_ref": None if preparation is None else preparation["preparation_ref"],
    }
    intent_ref = put_data(artifacts, duet_id, "checker_inputs", intent)
    if preparation is not None and preparation["status"] != "prepared":
        return put_data(artifacts, duet_id, "checker_execution", {
            "intent_ref": intent_ref, "status": "unavailable", "result": None,
            "diagnostics": preparation["diagnostics"], "log_refs": preparation["log_refs"],
            "returncode": None, "backend": None,
        })
    base = runs.root / "checking_instruments"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = Path(tempfile.mkdtemp(prefix="execution-", dir=base))
    inputs, scratch = root / "inputs", root / "scratch"
    inputs.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)
    for directory, files in (("program", program["files"]), ("target", fixture["files"])):
        (inputs / directory).mkdir(mode=0o700)
        for name, text in files.items():
            path = inputs / directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    (inputs / "request.json").write_text(canonical_json({
        "entrypoint": program["entrypoint"], "materialization": fixture["materialization"],
        "input": fixture["input"],
    }), encoding="utf-8")
    runtime_root = runs.runtime_sources_root / runtime.runtime_source_manifest_id.value
    dependencies = "" if preparation is None else preparation["site_packages"]
    mounts = [(str(inputs), str(inputs)), (str(runtime_root), str(runtime_root))]
    if dependencies:
        mounts.append((dependencies, dependencies))
    command = (str(executor.python_executable), "-I", "-S", "-B", "-c", _RUNNER,
               str(inputs), str(runtime_root), dependencies)
    result = await executor.prepare_environment(
        command, read_only_paths=tuple(mounts), writable_directory=scratch,
        environment={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                     "HOME": str(scratch), "TMPDIR": str(scratch)}, network_access=False,
    )
    logs = [{"stream": stream, "content_hash": builds.put_blob(result[stream].encode("utf-8")).value}
            for stream in ("stdout", "stderr")]
    try:
        value = json.loads(result["stdout"])
        if (result["returncode"] != 0 or not isinstance(value, dict)
                or not ((value.get("status") == "completed" and set(value) == {"status", "result"})
                        or (value.get("status") == "error" and set(value) == {"status", "error"}))):
            raise ValueError("checking process did not return a complete observation")
    except (ValueError, TypeError) as exc:
        value = {"status": "error", "error": str(exc)}
    return put_data(artifacts, duet_id, "checker_execution", {
        "intent_ref": intent_ref, "status": value["status"], "result": value.get("result"),
        "diagnostics": [] if value["status"] == "completed" else [{"message": value["error"]}],
        "log_refs": logs, "returncode": result["returncode"], "backend": result["backend"],
    })


def read_execution(artifacts, duet_id, reference, *, program, fixture, subject):
    row = read_reference(artifacts, reference, duet_id)
    if row["kind"] != "experiment.checker_execution.v1":
        raise ValueError("checker evidence must be a host-recorded instrument execution")
    record = row["record"]
    intent = read_reference(artifacts, record["intent_ref"], duet_id)
    if intent["kind"] != "experiment.checker_inputs.v1" or any(
        canonical_json(intent["record"][key]) != canonical_json(value)
        for key, value in (("program", program), ("fixture", fixture), ("subject", subject))
    ):
        raise ValueError("checker execution differs from its exact program, inputs or subject")
    return record
