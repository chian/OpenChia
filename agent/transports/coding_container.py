"""A per-turn container shell for a coding agent's diagnostic commands.

The coding model loop stays on the host. Only command execution moves into a
container, the way a CWL runner executes a tool: the coding workspace is the
only writable mount (at its own absolute path), OpenChia's sources are mounted
read-only as context, the root filesystem is read-only, every capability is
dropped, there is no network, and the process runs as the workspace owner so
created files stay owned by the host user.

One container lives for the whole turn (``docker run -d … sleep``); each command
is a ``docker exec``. A timeout or interrupt removes the container, which kills
everything running inside it; the next command starts a fresh one. A runtime
that cannot start is reported to the caller, never replaced by a host shell.
"""

from __future__ import annotations

import secrets
import subprocess
import threading
from pathlib import Path
from typing import Sequence

# no-tmp: ok — tmpfs mount target inside the Linux container's own mount namespace, never host scratch
_TMPFS = "/tmp:rw,nosuid,nodev,size=256m"
CONTEXT_ROOT = "/ctx/openchia"
_START_TIMEOUT = 120


class ContainerShellError(RuntimeError):
    """The container shell could not be started or used."""


class ContainerCommandShell:
    """Run shell commands for one coding turn inside an isolated container."""

    def __init__(self, *, cli: str | Path, image: str, workspace: str | Path,
                 read_only_mounts: Sequence[tuple[str | Path, str]] = (),
                 resource_arguments: Sequence[str] = (),
                 environment: dict[str, str] | None = None):
        self._cli = str(cli)
        self._image = image
        self._workspace = Path(workspace).resolve()
        self._mounts = tuple((str(Path(source).resolve()), str(target)) for source, target in read_only_mounts)
        self._resources = tuple(resource_arguments)
        self._environment = dict(environment or {})
        self._name: str | None = None
        self._lock = threading.Lock()
        self._closed = False

    # -- lifecycle --------------------------------------------------------------------------

    def run_arguments(self, name: str) -> list[str]:
        owner = self._workspace.stat()
        workspace = str(self._workspace)
        arguments = [
            self._cli, "run", "--detach", "--rm", "--name", name,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--user", f"{owner.st_uid}:{owner.st_gid}",
            # no-tmp: ok — HOME/TMPDIR point at the container's own tmpfs, never host scratch
            "--tmpfs", _TMPFS, "--env", "HOME=/tmp", "--env", "TMPDIR=/tmp",
            "--workdir", workspace, *self._resources,
            "--volume", f"{workspace}:{workspace}:rw",
        ]
        for source, target in self._mounts:
            arguments.extend(("--volume", f"{source}:{target}:ro"))
        for key in sorted(self._environment):
            arguments.extend(("--env", f"{key}={self._environment[key]}"))
        arguments.extend((self._image, "sleep", "infinity"))
        return arguments

    def _ensure_container(self) -> str:
        with self._lock:
            if self._closed:
                raise ContainerShellError("container shell is closed")
            if self._name is not None:
                return self._name
            name = f"openchia-coder-{secrets.token_hex(8)}"
            started = subprocess.run(
                self.run_arguments(name), stdin=subprocess.DEVNULL, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=_START_TIMEOUT,
            )
            if started.returncode != 0:
                raise ContainerShellError(
                    "could not start the coding container: " + (started.stderr or started.stdout).strip()[-800:]
                )
            self._name = name
            return name

    def _remove(self) -> None:
        with self._lock:
            name, self._name = self._name, None
        if name is not None:
            subprocess.run([self._cli, "rm", "--force", name], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=60)

    def interrupt(self) -> None:
        self._remove()

    def close(self) -> None:
        self._closed = True
        self._remove()

    # -- commands ---------------------------------------------------------------------------

    def run(self, command: str, timeout: int) -> str:
        """Execute *command* with ``sh -c`` in the workspace; return a status line and output."""
        try:
            name = self._ensure_container()
        except (ContainerShellError, OSError, subprocess.SubprocessError) as exc:
            return f"error: container shell unavailable ({exc}); no host shell fallback"
        process = subprocess.Popen(
            [self._cli, "exec", "--workdir", str(self._workspace), name, "sh", "-c", command],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            output, _ = process.communicate(timeout=timeout)
            return f"exit {process.returncode}\n{output or ''}"
        except subprocess.TimeoutExpired:
            # Killing the exec client leaves the process running inside the
            # container; removing the container kills everything it started.
            self._remove()
            process.kill()
            output, _ = process.communicate()
            return f"timed out after {timeout}s (container removed)\n{output or ''}"


def container_shell_for(executor, workspace: str | Path) -> ContainerCommandShell | None:
    """A container shell matching the Run's container executor, or ``None`` for other backends.

    Reuses the executor's container CLI, digest-pinned image and resource
    ceiling. OpenChia's own sources are mounted read-only at ``/ctx/openchia``
    (on ``PYTHONPATH``) so diagnostics can import its libraries without the
    coder browsing the host.
    """
    from episode_runtime.container_executor import ContainerRunExecutor, container_resource_arguments

    if not isinstance(executor, ContainerRunExecutor):
        return None
    return ContainerCommandShell(
        cli=executor.runtime.cli, image=executor.runtime.image_id, workspace=workspace,
        read_only_mounts=((executor.repository_root, CONTEXT_ROOT),),
        resource_arguments=container_resource_arguments(executor.resources),
        environment={"PYTHONPATH": CONTEXT_ROOT, "PYTHONDONTWRITEBYTECODE": "1"},
    )


__all__ = ["CONTEXT_ROOT", "ContainerCommandShell", "ContainerShellError", "container_shell_for"]

