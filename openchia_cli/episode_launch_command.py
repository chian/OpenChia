"""One launch command parser for foreground and background Duets."""
from __future__ import annotations

import shlex


def launch_command(host, arguments: str):
    parts = shlex.split(arguments)
    action = parts[0] if parts else "status"
    replace_existing = action == "apply" and parts[-1] == "--replace"
    if replace_existing:
        parts.pop()
    handlers = {
        "status": (0, host.launch_status),
        "calls": (0, host.launch_calls),
        "preview": (0, host.preview_launch),
        "approve": (1, host.approve_launch),
        "apply": (2, lambda proposal, path: host.apply_launch_proposal(proposal, path, replace_existing=replace_existing)),
        "load": (1, host.configure_launch),
        "reuse": (1, host.reuse_launch),
        "show": (1, host.launch_details),
        "reload": (0, host.reload_launch),
    }
    selected = handlers.get(action)
    if selected is None or len(parts[1:]) != selected[0]:
        raise ValueError("Usage: /launch [status|preview|approve HASH|apply PROPOSAL_ID FILE [--replace]|calls|show LAUNCH_ID|load FILE|reload|reuse LAUNCH_ID]")
    return selected[1](*parts[1:])
