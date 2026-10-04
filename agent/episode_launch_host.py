"""Durable launch selection and receipts on the existing Duet event store."""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from agent.duet_contracts import DuetProvenance, canonical_json
from agent.episode_contracts import Sha256Digest
from agent.episode_launch import LaunchConfigurationError, read_launch_spec, resolve_launch, validate_launch_spec
from agent.episode_launch_transport import LaunchModelTransport


def resolve_approved_launch(store, duet_id, *, configuration_hash=None, model_types=(), frozen_record=None):
    """Resolve the current human-approved launch for any host execution entry."""
    events = store.events(duet_id)
    selections = [event for event in events if event["event_type"] == "launch_configuration_selected"]
    approvals = [event for event in events if event["event_type"] == "launch_configuration_approved"]
    if not selections:
        raise LaunchConfigurationError("Select a launch file with /launch load FILE")
    selection = selections[-1]["record"]
    spec = selection["spec"]
    if selection["mode"] == "resolve":
        spec = read_launch_spec(spec["source_file"])
    if frozen_record is None and configuration_hash is not None:
        recorded = [
            event["record"]["configuration"] for event in events
            if event["event_type"] == "model_launch_resolved"
            and event["record"]["configuration_hash"] == configuration_hash
        ]
        if recorded:
            frozen_record = recorded[-1]
    if frozen_record is not None:
        frozen_hash = Sha256Digest.of_bytes(canonical_json(frozen_record).encode()).value
        if configuration_hash is None or frozen_hash != configuration_hash:
            raise LaunchConfigurationError("Frozen launch record requires its exact requested configuration hash")
    launch = resolve_launch(spec, frozen_record=frozen_record)
    if (
        not approvals
        or approvals[-1]["provenance"] != DuetProvenance.HUMAN_APPROVAL.value
        or approvals[-1]["record"]["selection_id"] != selection["selection_id"]
        or approvals[-1]["record"]["configuration_hash"] != launch.configuration_hash
    ):
        raise LaunchConfigurationError("Human launch approval required. Review /launch preview, then /launch approve HASH.")
    if configuration_hash is not None and configuration_hash != launch.configuration_hash:
        raise LaunchConfigurationError("Requested launch differs from the current human-approved configuration.")
    unknown = set(model_types) - launch.model_slot_catalog().keys()
    if unknown:
        raise LaunchConfigurationError(f"Materialized functions require missing model slots: {sorted(unknown)}")
    return selection, launch, {
        "duet_id": duet_id,
        "event_sequence": approvals[-1]["sequence"],
        "selection_id": selection["selection_id"],
        "configuration_hash": launch.configuration_hash,
    }


def resolved_launch_record(launch, *, selection, launch_id, kind, subject_id):
    """Keep approved routing separate from the environment actually launching it."""
    from importlib.metadata import PackageNotFoundError, version
    from openchia_cli.version_info import get_version_info

    source_root = Path(__file__).resolve().parents[1]
    paths = ("agent/episode_launch.py", "agent/episode_launch_host.py", "agent/episode_launch_transport.py",
             "agent/model_call_recovery.py", "agent/model_call_recovery_policy.py",
             "agent/auxiliary_client.py", "agent/codex_responses_adapter.py", "agent/anthropic_adapter.py")
    code = get_version_info()
    packages = {}
    for package in ("openai", "anthropic", "httpx"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {
        "launch_id": launch_id, "kind": kind, "subject_id": subject_id,
        "configuration_hash": launch.configuration_hash, "mode": selection["mode"],
        "reused_launch_id": selection.get("reused_launch_id"),
        "configuration": launch.record,
        "code": {"commit": code.commit, "branch": code.branch, "dirty": code.dirty},
        "client_packages": packages,
        "code_hashes": {path: Sha256Digest.of_bytes((source_root / path).read_bytes()).value for path in paths},
    }


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
        with self._launch_lock:
            self._launch_event("launch_configuration_selected", {
                "spec": spec, "mode": "resolve", "selection_id": uuid.uuid4().hex,
            }, human=True)
        return self.launch_status()

    def reuse_launch(self, launch_id: str) -> dict:
        launch = self.launch_details(launch_id)
        snapshot = launch["configuration"]
        with self._launch_lock:
            self._launch_event("launch_configuration_selected", {
                "spec": snapshot["resolved_spec"], "mode": "reuse", "reused_launch_id": launch_id,
                "selection_id": uuid.uuid4().hex,
            }, human=True)
        return self.launch_status()

    def propose_launch(self, configuration: dict) -> dict:
        """Save a nonsecret model proposal; only human CLI actions select or approve it."""
        spec = validate_launch_spec(configuration)
        spec.pop("source_file", None)
        proposal_id = Sha256Digest.of_bytes(canonical_json(spec).encode()).value
        self.store.append_event(
            duet_id=self.identity.duet_id.value, event_type="launch_configuration_proposed",
            provenance=DuetProvenance.LLM_PROPOSAL.value,
            record={"proposal_id": proposal_id, "configuration": spec},
        )
        return {"proposal_id": proposal_id, "configuration": spec,
                "next_action": f"Human: /launch apply {proposal_id} FILE, then /launch preview and /launch approve HASH"}

    def apply_launch_proposal(self, proposal_id: str, path: str, *, replace_existing: bool = False) -> dict:
        from utils import atomic_write_text

        with self._launch_lock:
            proposals = self._launch_events("launch_configuration_proposed")
            matches = [item for item in proposals if item["proposal_id"] == proposal_id]
            if not matches:
                raise LaunchConfigurationError("Launch proposal ID is not recorded for this Duet")
            target = Path(path).expanduser().resolve()
            if target.suffix != ".json":
                raise LaunchConfigurationError("Choose a .json launch file")
            previous_hash = None
            if target.exists():
                previous_hash = Sha256Digest.of_bytes(target.read_bytes()).value
                if not replace_existing:
                    try:
                        read_launch_spec(target)
                    except (ValueError, OSError):
                        raise LaunchConfigurationError(
                            "The destination is not a valid current launch file. "
                            "To replace that exact file, repeat /launch apply PROPOSAL_ID FILE --replace. "
                            "Replacement does not archive its contents."
                        ) from None
            spec = matches[-1]["configuration"]
            atomic_write_text(target, json.dumps(spec, indent=2) + "\n")
            # Record identity, not arbitrary prior text that might contain secrets.
            self._launch_event("launch_proposal_applied", {
                "proposal_id": proposal_id, "path": str(target),
                "previous_content_hash": previous_hash, "replace_existing": replace_existing,
            }, human=True)
            return self.configure_launch(str(target))

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
        context = self.launch_design_context()
        spec = context.get("configuration", {})
        return {key: value for key, value in {
            "state": context["state"], "selected": selection,
            "configuration_hash": context.get("configuration_hash"),
            "approved": context.get("approved", False),
            "model_slots": context.get("model_slots"),
            "builder_slots": spec.get("builder_slots"),
            "env_files": spec.get("env_files"),
            "issue": context.get("issue"), "next_action": context.get("next_action"),
            "latest_proposal_id": (context["latest_proposal"] or {}).get("proposal_id"),
            "launches": [
                {key: row[key] for key in ("launch_id", "kind", "subject_id", "configuration_hash", "mode")}
                for row in launches
            ],
        }.items() if value is not None}

    def launch_calls(self) -> list[dict]:
        return self._launch_events("model_launch_call")

    def preview_launch(self) -> dict:
        with self._launch_lock:
            selection, launch = self._resolve_selected_launch()
            return {"configuration_hash": launch.configuration_hash, "configuration": launch.record,
                    "approved": self._launch_is_approved(selection, launch),
                    "next_action": f"/launch approve {launch.configuration_hash}"}

    def _resolve_selected_launch(self):
        selected = self._launch_events("launch_configuration_selected")
        if not selected:
            raise LaunchConfigurationError("Select a launch file with /launch load FILE")
        selection = selected[-1]
        spec = selection["spec"]
        if selection["mode"] == "resolve":
            spec = read_launch_spec(spec["source_file"])
        return selection, resolve_launch(spec)

    def _launch_is_approved(self, selection, launch) -> bool:
        approvals = self._launch_events("launch_configuration_approved")
        return bool(approvals and approvals[-1]["selection_id"] == selection["selection_id"]
                    and approvals[-1]["configuration_hash"] == launch.configuration_hash)

    def approve_launch(self, configuration_hash: str) -> dict:
        """Human-only approval of the resolved settings reviewed with /launch preview."""
        with self._launch_lock:
            selection, launch = self._resolve_selected_launch()
            if configuration_hash != launch.configuration_hash:
                raise LaunchConfigurationError("Launch settings changed. Review /launch preview and approve its exact hash.")
            self.build_store.put_blob(launch.public_json.encode())
            self.store.append_event(
                duet_id=self.identity.duet_id.value, event_type="launch_configuration_approved",
                provenance=DuetProvenance.HUMAN_APPROVAL.value,
                record={"selection_id": selection["selection_id"], "configuration_hash": launch.configuration_hash},
            )
            return {"approved": True, "configuration_hash": launch.configuration_hash}

    def _require_approved_launch(self, *, model_types=()):
        with self._launch_lock:
            selection, launch, _ = resolve_approved_launch(
                self.store, self.identity.duet_id.value, model_types=model_types
            )
            return selection, launch

    def launch_design_context(self) -> dict:
        """Current nonsecret setup returned through duet_status, not the cached prompt."""
        proposals = self._launch_events("launch_configuration_proposed")
        context = {
            "state": "needs_launch_file",
            "suggested_slot_names": ["reasoning", "fast"],
            "setup_questions": [
                "Which project directory and existing launch file should this workflow use, or shall we prepare one?",
                "Which models, endpoints, reasoning settings and credential references should fill the shared model slots?",
                "Which project .env files hold those credential references?",
            ],
            "latest_proposal": proposals[-1] if proposals else None,
            "external_services": {"allowed_hosts": sorted(self.egress_hosts),
                                  "credential_names": sorted(self.egress_credentials)},
        }
        if not self._launch_events("launch_configuration_selected"):
            return context
        try:
            preview = self.preview_launch()
        except (ValueError, OSError) as exc:
            return {**context, "state": "needs_configuration", "issue": str(exc),
                    "next_action": "Correct the selected launch file or its explicit credential references, then /launch preview"}
        spec = preview["configuration"]["resolved_spec"]
        return {**context,
                "latest_proposal": {"proposal_id": proposals[-1]["proposal_id"]} if proposals else None,
                "configuration": spec, "configuration_hash": preview["configuration_hash"],
                "approved": preview["approved"], "next_action": preview["next_action"],
                "state": "approved" if preview["approved"] else "needs_human_approval",
                "model_slots": {slot: {"route": route, **spec["routes"][route]}
                                for slot, route in spec["model_slots"].items()}}

    def _prepare_model_launch(self, kind: str, subject_id: str, *, model_types=()):
        selection, launch = self._require_approved_launch(model_types=model_types)
        self.build_store.put_blob(launch.public_json.encode())
        launch_id = f"model_launch_{uuid.uuid4().hex}"
        self._launch_event("model_launch_resolved", resolved_launch_record(
            launch, selection=selection, launch_id=launch_id, kind=kind, subject_id=subject_id,
        ))
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
