from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.openchia_execution_boundary import (
    IsolatedExecutorAttestation,
    OpenChiaExecutionBoundary,
)


def _boundary(workspace: Path, protected: Path, *, attested: bool = False, sessions=()):
    return OpenChiaExecutionBoundary(
        workspace_roots=(workspace,),
        protected_roots=(protected,),
        isolated_executor=(
            IsolatedExecutorAttestation("sandbox", True, True, True, True)
            if attested else None
        ),
        owned_process_sessions=frozenset(sessions),
    )


def test_write_and_patch_allow_only_canonical_workspace_paths(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    boundary = _boundary(workspace, protected)
    assert boundary.authorize("write_file", {"path": "result.txt", "content": "ok"}) is None
    assert boundary.authorize("patch", {"mode": "replace", "path": str(workspace / "result.txt")}) is None
    outside = boundary.authorize("write_file", {"path": str(tmp_path / "outside.txt")})
    assert outside["error"] == "openchia_filesystem_boundary"


def test_parent_traversal_and_symlink_escape_are_rejected(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    (workspace / "escape").symlink_to(protected, target_is_directory=True)
    boundary = _boundary(workspace, protected)
    traversal = boundary.authorize("write_file", {"path": "../host/runtime.py"})
    symlink = boundary.authorize("write_file", {"path": "escape/runtime.py"})
    assert traversal["error"] == "openchia_filesystem_boundary"
    assert symlink["error"] == "openchia_runtime_immutable"


def test_v4a_patch_cannot_hide_host_target(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    boundary = _boundary(workspace, protected)
    denial = boundary.authorize(
        "patch",
        {
            "mode": "patch",
            "patch": f"*** Begin Patch\n*** Update File: {protected / 'runtime.py'}\n@@\n-old\n+new\n*** End Patch",
        },
    )
    assert denial["error"] == "openchia_runtime_immutable"


def test_hardlink_alias_to_host_file_is_rejected(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    host_file = protected / "runtime.py"
    host_file.write_text("trusted")
    alias = workspace / "alias.py"
    alias.hardlink_to(host_file)
    denial = _boundary(workspace, protected).authorize("write_file", {"path": str(alias)})
    assert denial["error"] == "openchia_filesystem_alias"


def test_nested_mount_alias_is_rejected(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    mounted = workspace / "mounted"
    workspace.mkdir()
    protected.mkdir()
    mounted.mkdir()
    real_is_mount = Path.is_mount
    monkeypatch.setattr(
        Path,
        "is_mount",
        lambda self: self == mounted or real_is_mount(self),
    )
    denial = _boundary(workspace, protected).authorize(
        "write_file", {"path": str(mounted / "result.txt")}
    )
    assert denial["error"] == "openchia_filesystem_alias"


@pytest.mark.parametrize("tool", ["terminal", "execute_code", "process_manage"])
def test_terminal_code_and_process_tools_fail_closed_without_isolation(tmp_path, tool) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    denial = _boundary(workspace, protected).authorize(
        tool, {"cmd": "kill -TERM 1", "session_id": "host"}
    )
    assert denial["error"] == "openchia_isolated_executor_required"


def test_host_restart_command_is_never_dispatched_without_isolation(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    denial = _boundary(workspace, protected).authorize(
        "terminal", {"cmd": "systemctl restart openchia"}
    )
    assert denial["error"] == "openchia_isolated_executor_required"


def test_process_manage_is_scoped_to_episode_owned_sessions(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    boundary = _boundary(workspace, protected, attested=True, sessions=("own-session",))
    assert boundary.authorize("process_manage", {"session_id": "own-session"}) is None
    denial = boundary.authorize("process_manage", {"session_id": "host-session"})
    assert denial["error"] == "openchia_process_ownership"


@pytest.mark.parametrize(
    "tool",
    ["duet_approve", "approval_update", "capability_grant", "credit_configuration_update"],
)
def test_episode_cannot_modify_control_plane_or_mint_capabilities(tmp_path, tool) -> None:
    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    denial = _boundary(workspace, protected).authorize(tool, {})
    assert denial["error"] == "openchia_control_plane_isolation"


def test_workspace_cannot_overlap_host_runtime(tmp_path) -> None:
    protected = tmp_path / "host"
    protected.mkdir()
    with pytest.raises(ValueError, match="overlap"):
        _boundary(protected / "workspace", protected)


def test_dispatch_checks_boundary_after_argument_rewrite_and_never_executes(
    tmp_path, monkeypatch
) -> None:
    from agent import tool_executor

    workspace = tmp_path / "workspace"
    protected = tmp_path / "host"
    workspace.mkdir()
    protected.mkdir()
    agent = SimpleNamespace(
        _openchia_execution_boundary=_boundary(workspace, protected)
    )
    monkeypatch.setattr(
        tool_executor,
        "_pre_tool_block",
        lambda _agent, ref: (None, {"path": str(protected / "runtime.py")}),
    )
    monkeypatch.setattr(tool_executor, "_emit_terminal_post_tool_call", lambda *_a, **_k: None)
    executed = []
    state = tool_executor._ManagedToolResult(
        result=None, args={}, middleware_trace=[], blocked=False, dispatched=False
    )
    result = tool_executor._dispatch_authorized_once(
        agent,
        state,
        tool_executor._ToolCallRef("write_file", {}, "task", "call", []),
        execute=lambda args: executed.append(args),
        scope_block=None,
        display_index=None,
        begin_execution=None,
        authorization_gate=None,
    )
    assert "openchia_runtime_immutable" in result
    assert state.blocked is True
    assert executed == []
