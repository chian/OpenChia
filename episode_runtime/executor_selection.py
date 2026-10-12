"""Pick the Run executor: a container by default, systemd only when selected.

ADR 0005: containers are the default Target Workflow execution backend on
Linux and macOS; systemd is an explicitly selectable Linux option. The presence
or version of host ``systemd-run`` must not select the backend, and a backend
whose prerequisites are missing fails at setup instead of falling back.
"""
from __future__ import annotations

import os
from pathlib import Path

from .container_executor import DEFAULT_CONTAINER_IMAGE, make_container_run_executor_factory
from .executor import RunExecutorFactory, make_systemd_run_executor_factory

#: ``OPENCHIA_RUN_EXECUTOR``: ``auto`` (default, = ``container``), ``systemd`` or ``container``.
EXECUTOR_BACKEND_ENV = "OPENCHIA_RUN_EXECUTOR"
#: ``OPENCHIA_CONTAINER_IMAGE``: the image whose interpreter runs the worker.
CONTAINER_IMAGE_ENV = "OPENCHIA_CONTAINER_IMAGE"
def resolve_executor_backend(requested: str | None = None) -> str:
    """Return the selected backend: an explicit request, else the environment, else ``container``.

    Host facts deliberately play no part (ADR 0005): ``auto`` means the
    container default on every platform, and systemd runs only when selected
    with ``OPENCHIA_RUN_EXECUTOR=systemd`` (or ``requested="systemd"``).
    """
    selected = (requested or os.environ.get(EXECUTOR_BACKEND_ENV) or "auto").strip().lower()
    if selected == "auto":
        return "container"
    if selected not in {"systemd", "container"}:
        raise ValueError(f"{EXECUTOR_BACKEND_ENV} must be auto, systemd or container, not {selected!r}")
    return selected


def make_run_executor_factory(
    *,
    repository_root: str | Path,
    backend: str | None = None,
    image: str | None = None,
) -> RunExecutorFactory:
    selected = resolve_executor_backend(backend)
    if selected == "systemd":
        return make_systemd_run_executor_factory(repository_root=repository_root)
    return make_container_run_executor_factory(
        repository_root=repository_root,
        image=image or os.environ.get(CONTAINER_IMAGE_ENV) or DEFAULT_CONTAINER_IMAGE,
    )


__all__ = [
    "CONTAINER_IMAGE_ENV",
    "EXECUTOR_BACKEND_ENV",
    "make_run_executor_factory",
    "resolve_executor_backend",
]
