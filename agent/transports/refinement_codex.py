"""Codex-specific setup and event projection for Implementer's coding capability.

The existing app-server session owns the model/tool loop and process lifecycle.
This adapter does not configure a Target Workflow execution environment.
"""

import json
from dataclasses import asdict
from functools import partial
from pathlib import Path

from agent.codex_headers import CODEX_AUX_BASE_URL, codex_account_headers
from agent.codex_responses_adapter import _wire_model_identity
from agent.refinement_coding import CodingTurn
from agent.transports.codex_app_server import CodexAppServerClient
from agent.transports.codex_app_server_session import CodexAppServerSession


_ACTIVITY_KINDS = {
    "item/started": "item_started",
    "item/completed": "item_completed",
    "turn/started": "turn_started",
    "turn/completed": "turn_completed",
    "error": "api_error",
}


class _PinnedCodexClient(CodexAppServerClient):
    def __init__(self, *, binding, cwd, **kwargs):
        self.binding = binding
        route = binding.record["route"]
        if route["api_mode"] != "codex_responses" or route["base_url"].rstrip("/") != CODEX_AUX_BASE_URL:
            raise ValueError(
                "Implementer's Codex adapter requires the owning Duet's official Codex route; "
                "no alternate provider or ambient Codex account was selected."
            )
        self.account_id = codex_account_headers(binding.api_key).get("ChatGPT-Account-ID")
        if not self.account_id:
            raise ValueError("The owning Duet has no usable Codex account credential.")
        settings = {
            "model_provider": "openai",
            "model": _wire_model_identity(route["model"]),
            "approval_policy": "never",
            # Standard inherited Codex coding mode. Do not install host policy
            # or silently escalate when the native CLI cannot use this mode.
            "sandbox_mode": "workspace-write",
            "cli_auth_credentials_store": "ephemeral",
            "forced_login_method": "chatgpt",
            "forced_chatgpt_workspace_id": self.account_id,
            "features.multi_agent": False,
            "agents.enabled": False,
            "features.apps": False,
            "features.memories": False,
            "features.plugins": False,
            "features.remote_plugin": False,
            "features.hooks": False,
            "features.skill_mcp_dependency_install": False,
            "web_search": "disabled",
            "analytics.enabled": False,
            "feedback.enabled": False,
            "check_for_update_on_startup": False,
            "allow_login_shell": False,
            "shell_environment_policy.inherit": "core",
            "project_doc_max_bytes": 0,
            "openai_base_url": route["base_url"],
            "chatgpt_base_url": "https://chatgpt.com/backend-api/",
        }
        reasoning = route.get("reasoning") or {}
        if reasoning.get("effort"):
            settings["model_reasoning_effort"] = reasoning["effort"]
        args = [arg for key, value in settings.items() for arg in ("-c", f"{key}={json.dumps(value)}")]
        super().__init__(
            **kwargs, cwd=str(cwd), extra_args=args,
            inherit_credentials=False, inherit_delegation=False,
        )

    def initialize(self, **kwargs):
        result = super().initialize(**{**kwargs, "capabilities": {"experimentalApi": True}})
        self.request("account/login/start", {
            "type": "chatgptAuthTokens", "accessToken": self.binding.api_key,
            "chatgptAccountId": self.account_id,
        })
        return result

class CodexCodingSession(CodexAppServerSession):
    runtime_id = "codex_app_server"

    def __init__(self, *, binding, workspace, state_dir, instructions, resume_thread_id, on_event):
        from openchia_cli.codex_runtime_switch import get_configured_codex_binary
        from openchia_cli.config import load_config_readonly

        home = Path(state_dir)
        home.mkdir(mode=0o700, parents=True, exist_ok=True)

        def observe(note):
            kind = _ACTIVITY_KINDS.get(note.get("method"))
            if kind is not None:
                on_event({"kind": kind, "native": note,
                          "error": note.get("params", {}).get("error") if kind == "api_error" else None})

        super().__init__(
            cwd=str(workspace), codex_home=str(home),
            codex_bin=get_configured_codex_binary(load_config_readonly()),
            model=_wire_model_identity(binding.record["route"]["model"]),
            model_provider="openai",
            developer_instructions=instructions,
            resume_thread_id=resume_thread_id, on_event=observe,
            client_factory=partial(_PinnedCodexClient, binding=binding, cwd=workspace),
        )

    def run_turn(self, prompt, *, turn_timeout=None):
        result = super().run_turn(prompt, turn_timeout=turn_timeout)
        return CodingTurn(
            final_text=result.final_text, thread_id=result.thread_id, turn_id=result.turn_id,
            tool_iterations=result.tool_iterations, interrupted=result.interrupted,
            error=result.error, native_result=asdict(result),
        )
