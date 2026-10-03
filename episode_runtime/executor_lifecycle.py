"""Read-only stopped-attempt checks used before continuation, never a runner."""

import asyncio
from pathlib import Path

from .contracts import ExecutorKind


async def verify_stopped_executor(executor, attestation):
    """Terminal audit alone does not establish that an old worker has stopped."""
    if attestation.executor_kind is ExecutorKind.SYSTEMD:
        return await _systemd_stopped(executor, attestation)
    return await _container_stopped(executor, attestation)


async def _systemd_stopped(executor, attestation):
    from .executor import RunExecutionError, _boot_id, _command_output, _show_unit

    if not hasattr(executor, "systemctl") or _boot_id() != attestation.boot_id:
        raise RunExecutionError("continuation cannot verify the original systemd host/boot")
    units = await _command_output(
        str(executor.systemctl), "--user", "list-units", "--all", "--plain",
        "--no-legend", "--no-pager", attestation.executor_unit_name,
    )
    if units.strip():
        values = await _show_unit(executor.systemctl, attestation.executor_unit_name)
        if (
            values["ActiveState"] not in {"inactive", "failed"}
            or values["MainPID"] != "0"
            or values["Description"] != attestation.launch_description
            or values["InvocationID"] not in {"", attestation.executor_invocation_id}
        ):
            raise RunExecutionError("previous executor is not verified stopped with its exact identity")
    path = Path("/sys/fs/cgroup") / attestation.cgroup_path.lstrip("/") / "cgroup.events"
    try:
        events = await asyncio.to_thread(path.read_text, encoding="ascii")
    except FileNotFoundError:
        events = "populated 0"
    rows = dict(line.split() for line in events.splitlines())
    if rows.get("populated") != "0":
        raise RunExecutionError("previous executor cgroup still contains processes")
    return {"attestation_id": attestation.attestation_id.value, "executor_kind": attestation.executor_kind.value, "stopped": True}


async def _container_stopped(executor, attestation):
    from .container_executor import _cli_output
    from .executor import RunExecutionError

    if not hasattr(executor, "runtime") or not hasattr(executor, "_inspect_container"):
        raise RunExecutionError("continuation needs the original container executor backend")
    found = await _cli_output(
        executor.runtime.cli, "ps", "--all", "--no-trunc", "--quiet",
        "--filter", "id=" + attestation.executor_invocation_id,
    )
    identifiers = found.split()
    if identifiers:
        if identifiers != [attestation.executor_invocation_id]:
            raise RunExecutionError("container lookup differs from the exact previous executor")
        info = await executor._inspect_container(attestation.executor_invocation_id)
        state = info.get("State") or {}
        if (
            info.get("Id") != attestation.executor_invocation_id
            or (info.get("Config", {}).get("Labels") or {}).get("openchia.launch") != attestation.launch_description
            or state.get("Status") not in {"exited", "dead"}
            or state.get("Running") is not False
            or state.get("Restarting") is not False
            or state.get("Pid") != 0
        ):
            raise RunExecutionError("previous container is not verified stopped")
    return {"attestation_id": attestation.attestation_id.value, "executor_kind": attestation.executor_kind.value, "stopped": True}
