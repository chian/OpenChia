"""Mechanical dispatch boundary for effect-capable OpenChia Episode tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any, Mapping, Optional

from agent.tool_dispatch_helpers import _extract_file_mutation_targets


_FILE_MUTATORS = frozenset({"write_file", "patch"})
_EXECUTION_TOOLS = frozenset({"terminal", "execute_code"})
_PROCESS_TOOLS = frozenset({"process_manage"})
_CONTROL_PLANE_MUTATORS = frozenset(
    {
        "duet_approve",
        "duet_revoke_approval",
        "duet_freeze_workflow",
        "duet_launch_workflow",
        "approval_update",
        "capability_grant",
        "credit_configuration_update",
    }
)


@dataclass(frozen=True)
class IsolatedExecutorAttestation:
    """Host-issued evidence for the mechanical task-execution boundary."""

    executor_id: str
    filesystem_namespace_isolated: bool
    process_namespace_isolated: bool
    process_ownership_enforced: bool
    host_runtime_read_only: bool

    @property
    def permits_effectful_recursion(self) -> bool:
        return all(
            (
                self.filesystem_namespace_isolated,
                self.process_namespace_isolated,
                self.process_ownership_enforced,
                self.host_runtime_read_only,
            )
        )


@dataclass(frozen=True)
class OpenChiaExecutionBoundary:
    """A fail-closed allowlist attached to one running Episode agent.

    File mutations are admitted only under explicit canonical workspace roots.
    Shell, code, and process operations additionally require a host-issued
    isolated-executor attestation; path checks alone are not a sandbox.
    """

    workspace_roots: tuple[Path, ...]
    protected_roots: tuple[Path, ...]
    isolated_executor: Optional[IsolatedExecutorAttestation] = None
    owned_process_sessions: frozenset[str] = field(default_factory=frozenset)
    allow_control_plane_mutation: bool = False

    def __post_init__(self) -> None:
        if not self.workspace_roots:
            raise ValueError("an Episode execution boundary needs a workspace root")
        workspaces = tuple(Path(item).expanduser().resolve() for item in self.workspace_roots)
        platform_root = Path(__file__).resolve().parents[1]
        protected = tuple(
            dict.fromkeys(
                (
                    *(Path(item).expanduser().resolve() for item in self.protected_roots),
                    platform_root,
                    Path(sys.executable).resolve(),
                )
            )
        )
        object.__setattr__(self, "workspace_roots", workspaces)
        object.__setattr__(self, "protected_roots", protected)
        for root in workspaces:
            if root == Path(root.anchor):
                raise ValueError("filesystem root cannot be an Episode workspace")
            if any(root == item or item in root.parents for item in protected):
                raise ValueError("Episode workspace cannot overlap a protected host root")

    @staticmethod
    def _beneath(path: Path, roots: tuple[Path, ...]) -> bool:
        return any(path == root or root in path.parents for root in roots)

    def _resolve_target(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise ValueError("file mutation target must be non-empty text")
        supplied = Path(raw).expanduser()
        if ".." in supplied.parts:
            raise ValueError("parent traversal is prohibited in Episode file mutations")
        if supplied.is_absolute():
            candidate = supplied
        else:
            candidate = self.workspace_roots[0] / supplied
        # resolve(strict=False) resolves every existing symlink hop, including
        # parent-directory symlinks, while retaining a not-yet-created leaf.
        return candidate.resolve(strict=False)

    def _alias_denial(self, target: Path, workspace: Path) -> Optional[str]:
        """Reject host aliases that canonical path containment cannot expose."""

        current = target if target.exists() else target.parent
        while current != workspace and workspace in current.parents:
            try:
                if current.is_mount():
                    return f"nested mount point is not an admitted workspace root: {current}"
            except OSError:
                return f"cannot verify mount boundary for {current}"
            current = current.parent
        try:
            if target.exists() and target.is_file() and target.stat().st_nlink > 1:
                return f"hard-linked mutation targets are prohibited: {target}"
        except OSError:
            return f"cannot verify link boundary for {target}"
        return None

    def authorize(self, tool_name: str, args: Mapping[str, Any]) -> Optional[dict[str, Any]]:
        if tool_name in _CONTROL_PLANE_MUTATORS and not self.allow_control_plane_mutation:
            return {
                "error": "openchia_control_plane_isolation",
                "message": "running Episodes cannot mutate contracts, approvals, capabilities, evidence acceptance, or credit policy",
            }
        if tool_name in _FILE_MUTATORS:
            try:
                targets = _extract_file_mutation_targets(tool_name, dict(args))
                if not targets:
                    raise ValueError("file mutation did not declare an exact target")
                resolved = tuple(self._resolve_target(item) for item in targets)
            except (TypeError, ValueError) as exc:
                return {"error": "openchia_filesystem_boundary", "message": str(exc)}
            for target in resolved:
                if self._beneath(target, self.protected_roots):
                    return {
                        "error": "openchia_runtime_immutable",
                        "message": f"Episode mutation targets protected host/runtime path {target}",
                    }
                if not self._beneath(target, self.workspace_roots):
                    return {
                        "error": "openchia_filesystem_boundary",
                        "message": f"Episode mutation target is outside its workspace: {target}",
                    }
                workspace = next(
                    root for root in self.workspace_roots
                    if target == root or root in target.parents
                )
                alias_denial = self._alias_denial(target, workspace)
                if alias_denial is not None:
                    return {
                        "error": "openchia_filesystem_alias",
                        "message": alias_denial,
                    }
            return None
        if tool_name in _EXECUTION_TOOLS | _PROCESS_TOOLS:
            if self.isolated_executor is None or not self.isolated_executor.permits_effectful_recursion:
                return {
                    "error": "openchia_isolated_executor_required",
                    "message": "terminal, code, and process tools require mechanical filesystem and process isolation",
                }
        if tool_name in _PROCESS_TOOLS:
            session = args.get("session_id") or args.get("process_id")
            if session is None or str(session) not in self.owned_process_sessions:
                return {
                    "error": "openchia_process_ownership",
                    "message": "process_manage is restricted to sessions owned by this Episode",
                }
        return None


__all__ = ["IsolatedExecutorAttestation", "OpenChiaExecutionBoundary"]
