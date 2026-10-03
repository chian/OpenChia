"""Durable launch selection and receipts on the existing Duet event store."""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from agent.duet_contracts import DuetProvenance
from agent.episode_contracts import Sha256Digest
from agent.episode_launch import LaunchConfigurationError, read_launch_spec, resolve_launch
from agent.episode_launch_transport import LaunchModelTransport


class EpisodeLaunchHostMixin:
    def _launch_events(self, kind: str) -> list[dict]:
        return [event["record"] for event in self.store.events(self.identity.duet_id.value)
                if event["event_type"] == kind]

    def _launch_event(self, kind: str, record: dict, *, human: bool = False) -> None:
        self.store.append_event(
            duet_id=self.identity.duet_id.value, event_type=kind,
            provenance=(DuetProvenance.HUMAN_INPUT if human else DuetProvenance.HOST_VALIDATION).value,
            record=record,
        )

    def configure_launch(self, path: str) -> dict:
        spec = read_launch_spec(path)
        self._launch_event("launch_configuration_selected", {"spec": spec, "mode": "resolve"}, human=True)
        return self.launch_status()

    def reuse_launch(self, launch_id: str) -> dict:
        launch = self.launch_details(launch_id)
        snapshot = launch["configuration"]
        self._launch_event("launch_configuration_selected", {
            "spec": snapshot["resolved_spec"], "mode": "reuse", "reused_launch_id": launch_id,
        }, human=True)
        return self.launch_status()

    def launch_details(self, launch_id: str) -> dict:
        launches = [row for row in self._launch_events("model_launch_resolved") if row["launch_id"] == launch_id]
        if len(launches) != 1:
            raise LaunchConfigurationError("launch ID is not recorded for this Duet")
        snapshot = json.loads(self.build_store.read_blob(launches[0]["configuration_hash"]))
        return {**launches[0], "configuration": snapshot}

    def reload_launch(self) -> dict:
        selected = self._launch_events("launch_configuration_selected")
        if not selected or not selected[-1]["spec"].get("source_file"):
            raise LaunchConfigurationError("Select a launch file with /launch load FILE")
        if selected[-1]["mode"] == "reuse":
            raise LaunchConfigurationError("A frozen launch is selected. Use /launch load FILE to switch back to file settings.")
        return self.configure_launch(selected[-1]["spec"]["source_file"])

    def launch_status(self) -> dict:
        selected = self._launch_events("launch_configuration_selected")
        launches = self._launch_events("model_launch_resolved")
        selection = None if not selected else {
            "mode": selected[-1]["mode"],
            "project": selected[-1]["spec"]["project"],
            "source_file": selected[-1]["spec"].get("source_file"),
            "reused_launch_id": selected[-1].get("reused_launch_id"),
        }
        return {"selected": selection, "launches": [
            {key: row[key] for key in ("launch_id", "kind", "subject_id", "configuration_hash", "mode")}
            for row in launches
        ]}

    def launch_calls(self) -> list[dict]:
        return self._launch_events("model_launch_call")

    def preview_launch(self) -> dict:
        selected = self._launch_events("launch_configuration_selected")
        if not selected:
            raise LaunchConfigurationError("Select a launch file with /launch load FILE")
        spec = selected[-1]["spec"]
        wants_session = any(route["auth"]["kind"] == "session" for route in spec["routes"].values())
        runtime = self._role_agent_kwargs("model_launch", "preview") if wants_session else None
        launch = resolve_launch(spec, session_runtime=runtime)
        return {"configuration_hash": launch.configuration_hash, "configuration": launch.record}

    def _prepare_model_launch(self, kind: str, subject_id: str, local_ids: set[str]):
        selected = self._launch_events("launch_configuration_selected")
        if not selected:
            raise LaunchConfigurationError("Select the project's model configuration with /launch load FILE before /build or /run")
        selection = selected[-1]
        spec = selection["spec"]
        unknown = set(spec["bindings"].get("episodes", {})) - local_ids
        if unknown:
            raise LaunchConfigurationError(f"model bindings name unknown Episode IDs: {sorted(unknown)}")
        wants_session = any(route["auth"]["kind"] == "session" for route in spec["routes"].values())
        runtime = self._role_agent_kwargs("model_launch", subject_id) if wants_session else None
        launch = resolve_launch(spec, session_runtime=runtime)
        digest = self.build_store.put_blob(launch.public_json.encode())
        launch_id = f"model_launch_{uuid.uuid4().hex}"
        source_root = Path(__file__).resolve().parents[1]
        paths = ("agent/episode_launch.py", "agent/episode_launch_host.py", "agent/episode_launch_transport.py",
                 "agent/auxiliary_client.py", "agent/codex_responses_adapter.py", "agent/anthropic_adapter.py")
        from openchia_cli.version_info import get_version_info
        from importlib.metadata import PackageNotFoundError, version
        code = get_version_info()
        packages = {}
        for package in ("openai", "anthropic", "httpx"):
            try:
                packages[package] = version(package)
            except PackageNotFoundError:
                packages[package] = None
        self._launch_event("model_launch_resolved", {
            "launch_id": launch_id, "kind": kind, "subject_id": subject_id,
            "configuration_hash": digest.value, "mode": selection["mode"],
            "reused_launch_id": selection.get("reused_launch_id"),
            "configuration": launch.record,
            "code": {"commit": code.commit, "branch": code.branch, "dirty": code.dirty},
            "client_packages": packages,
            "code_hashes": {path: Sha256Digest.of_bytes((source_root / path).read_bytes()).value for path in paths},
        })
        return launch_id, launch

    def _model_launch_transport(self, launch_id, launch, **kwargs):
        return LaunchModelTransport(launch, launch_id=launch_id,
            record_attempt=lambda record: self._launch_event("model_launch_call", record), **kwargs)

    @staticmethod
    def _model_node_path(local_id, plan) -> tuple[str, ...]:
        nodes = {node.local_id: node for node in plan.nodes}
        path = []
        while local_id is not None:
            node = nodes[local_id]
            path.append(node.grain_name)
            local_id = node.parent_local_id
        return tuple(reversed(path))
