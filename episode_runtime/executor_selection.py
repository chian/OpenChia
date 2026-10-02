"""Pick the Run executor for this host: systemd where it exists, a container elsewhere."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .container_executor import DEFAULT_CONTAINER_IMAGE, make_container_run_executor_factory
from .executor import RunExecutorFactory, make_systemd_run_executor_factory

#: ``OPENCHIA_RUN_EXECUTOR``: ``auto`` (default), ``systemd`` or ``container``.
EXECUTOR_BACKEND_ENV = "OPENCHIA_RUN_EXECUTOR"
#: ``OPENCHIA_CONTAINER_IMAGE``: the image whose interpreter runs the worker.
CONTAINER_IMAGE_ENV = "OPENCHIA_CONTAINER_IMAGE"
_SYSTEMD_RUN = Path("/usr/bin/systemd-run")


def resolve_executor_backend(
    requested: str | None = None,
    *,
    platform: str | None = None,
    systemd_available: bool | None = None,
) -> str:
    """Pick the backend from explicit host facts; the host's own are the default.

    ``platform`` and ``systemd_available`` are data so the decision is testable
    on any host without faking ``sys.platform`` (AGENTS.md, "Don't fake the
    host OS"); callers normally pass neither.
    """
    selected = (requested or os.environ.get(EXECUTOR_BACKEND_ENV) or "auto").strip().lower()
    if selected == "auto":
        host = sys.platform if platform is None else platform
        has_systemd = _SYSTEMD_RUN.exists() if systemd_available is None else systemd_available
        return "systemd" if host.startswith("linux") and has_systemd else "container"
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
