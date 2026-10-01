"""Concrete host for Duet design, validation, freeze, and human approval."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import threading
from typing import Any, Callable, Iterable, Mapping, Optional

from agent.duet_contracts import (
    ApprovalKind,
    DUET_PROTOCOL_TOOLS,
    DUET_SEARCH_TOOLS,
    OPENCHIA_CONTROL_PLANE_TOOLS,
    DuetIdentity,
    DuetPolicy,
    canonical_json,
    content_id,
)
from agent.duet_service import (
    DuetProtocolError,
    DuetService,
    EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
)
from agent.duet_store import DuetStore
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    OpaqueId,
    Sha256Digest,
)
from agent.interrupt_compat import request_hard_interrupt
from agent.openchia_agents import (
    bind_duet_agent,
    build_workflow_critic_agent,
)


WORKFLOW_REVIEW_LENSES = frozenset(
    {
        "contract_alignment",
        "measurement_evidence",
        "iteration_recovery",
        "capability_safety",
        "task_specific_skeptic",
    }
)


class OpenChiaHostError(RuntimeError):
    """The execution host cannot honor a frozen workflow."""


@dataclass(frozen=True)
class HumanActionReceipt:
    kind: str
    artifact_id: OpaqueId
    approval_id: OpaqueId


class OpenChiaHost:
    """Persistent authority and execution host for one interactive Duet."""

    def __init__(
        self,
        *,
        home: str | Path,
        session_id: str,
        available_tool_names: Iterable[str],
        agent_kwargs_factory: Callable[[str, str], dict[str, Any]],
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("OpenChia requires a non-empty session_id")
        if not callable(agent_kwargs_factory):
            raise TypeError("agent_kwargs_factory must be callable")
        self.root = Path(home).expanduser().resolve() / "openchia"
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = DuetStore(self.root / "duet.sqlite3")
        self.available_tool_names = frozenset(
            name
            for name in available_tool_names
            if isinstance(name, str)
            and name
            and name not in OPENCHIA_CONTROL_PLANE_TOOLS
        )
        self.agent_kwargs_factory = agent_kwargs_factory
        duet_tools = DUET_PROTOCOL_TOOLS | (
            DUET_SEARCH_TOOLS & self.available_tool_names
        )
        policy_fields = {"capability_allowlist": sorted(duet_tools)}
        policy_id = content_id("policy", policy_fields)
        self.policy = DuetPolicy(
            policy_id=policy_id,
            capability_allowlist=tuple(policy_fields["capability_allowlist"]),
        )
        self.identity = DuetIdentity(
            duet_id=OpaqueId.mint("duet", session_id),
            human_authority_id=OpaqueId.mint("human", f"local:{self.root}"),
            policy_id=policy_id,
            conversation_id=OpaqueId.mint("conversation", session_id),
        )
        self.service = DuetService(
            self.store,
            allowed_episode_capabilities=self.available_tool_names,
        )
        try:
            self.service.open_duet(self.identity, self.policy)
        except Exception:
            self.store.close()
            raise
        self._draft_write_lock = threading.RLock()
        self._duet_agent: Any = None

    def close(self) -> None:
        self.store.close()

    def bind_duet(self, agent: Any) -> Any:
        bound = bind_duet_agent(
            agent,
            service=self.service,
            identity=self.identity,
            policy=self.policy,
        )
        bound._duet_workflow_updater = self.record_duet_workflow_revision
        bound._openchia_draft_write_lock = self._draft_write_lock
        self._duet_agent = bound
        return bound

    @staticmethod
    def _chat_as_interruptible_child(
        parent_agent: Any,
        child_agent: Any,
        request: str,
    ) -> str:
        children = getattr(parent_agent, "_active_children", None)
        children_lock = getattr(parent_agent, "_active_children_lock", None)
        registered = isinstance(children, list) and children_lock is not None
        if registered:
            with children_lock:
                children.append(child_agent)
            hard_event = getattr(parent_agent, "_hard_interrupt_requested", None)
            if hard_event is not None and hard_event.is_set():
                request_hard_interrupt(
                    child_agent,
                    tool_reason="parent OpenChia turn stopped",
                )
            elif getattr(parent_agent, "_interrupt_requested", False):
                child_agent.interrupt()
        try:
            return child_agent.chat(request)
        finally:
            if registered:
                with children_lock:
                    if child_agent in children:
                        children.remove(child_agent)
            close = getattr(child_agent, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _parse_contract_review(payload: str) -> dict[str, Any]:
        text = payload.strip()
        if text.startswith("```"):
            first_newline = text.find("\n")
            text = text[first_newline + 1 :] if first_newline >= 0 else text
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("review lens did not return a JSON object")
            value = json.loads(text[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("review lens response must be a JSON object")
        if value.get("verdict") not in {"pass", "concern", "block"}:
            raise ValueError("review lens verdict is invalid")
        if not isinstance(value.get("summary"), str) or not isinstance(
            value.get("findings"), list
        ):
            raise ValueError("review lens response is incomplete")
        return {
            "verdict": value["verdict"],
            "summary": value["summary"][:4096],
            "findings": value["findings"][:12],
        }

    def _role_agent_kwargs(self, role: str, identity: str) -> dict[str, Any]:
        kwargs = self.agent_kwargs_factory(role, identity)
        if not isinstance(kwargs, dict):
            raise TypeError("agent_kwargs_factory must return a dictionary")
        return kwargs

    def review_episode_design(self) -> dict[str, Any]:
        snapshot = self.episode_workflow_configuration()
        if not snapshot["ready"]:
            raise DuetProtocolError(
                "design review requires a deterministically valid Episode workflow"
            )
        blueprint = snapshot["configuration"]
        blueprint_hash = Sha256Digest.of_record(blueprint)
        authority = self.service.workflow_admission_authority(
            self.identity.duet_id
        )
        latest = self.store.latest_artifact(
            duet_id=self.identity.duet_id.value,
            kind="workflow_shadow_review",
        )
        if (
            latest is not None
            and latest["record"].get("workflow_blueprint_hash")
            == blueprint_hash.value
            and latest["record"].get("admission_authority_hash")
            == authority.content_hash.value
        ):
            return {"accepted": True, "cached": True, **latest["record"]}
        workflow, deficits = self.service.validate_duet_workflow(
            self.identity.duet_id,
            blueprint,
        )
        if workflow is None or deficits:
            return {
                "accepted": False,
                "reason": "workflow_admission_failed",
                "deficits": [item.as_record() for item in deficits],
            }

        def review_lens(lens: str) -> tuple[str, dict[str, Any]]:
            critic = build_workflow_critic_agent(
                **self._role_agent_kwargs(
                    "workflow_critic",
                    f"{blueprint_hash.value}:{lens}",
                )
            )
            request = {
                "operation": "review_duet_episode_design",
                "lens": lens,
                "admission_authority": authority.as_record(),
                "workflow_blueprint_hash": blueprint_hash.value,
                "workflow": blueprint,
                "host_validation": {"admission_deficits": []},
            }
            return lens, self._parse_contract_review(
                self._chat_as_interruptible_child(
                    self._duet_agent,
                    critic,
                    canonical_json(request),
                )
            )

        lenses = tuple(sorted(WORKFLOW_REVIEW_LENSES))
        with ThreadPoolExecutor(
            max_workers=len(lenses),
            thread_name_prefix="openchia-explicit-review",
        ) as pool:
            reviews = dict(pool.map(review_lens, lenses))
        record = {
            "admission_authority_hash": authority.content_hash.value,
            "workflow_blueprint_hash": blueprint_hash.value,
            "workflow_hash": workflow.workflow_hash.value,
            "workflow_blueprint": workflow_blueprint_from_spec(workflow),
            "lenses": reviews,
        }
        artifact_id = content_id("review", record)
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=self.identity.duet_id.value,
            kind="workflow_shadow_review",
            revision=int(snapshot["revision"]),
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return {
            "accepted": True,
            "cached": False,
            "review_artifact_id": artifact_id.value,
            **record,
        }

    def episode_workflow_configuration(self) -> dict[str, Any]:
        duet = self.store.get_duet(self.identity.duet_id.value)
        if duet is None:
            raise OpenChiaHostError("active Duet record is missing")
        draft = self.store.latest_artifact(
            duet_id=self.identity.duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
        )
        if draft is None:
            raise DuetProtocolError(
                "no Episode workflow draft exists yet; design the Episode tree "
                "with the Duet first"
            )
        blueprint = draft["record"].get("workflow_blueprint")
        if not isinstance(blueprint, Mapping):
            raise OpenChiaHostError(
                "stored Episode workflow draft has no structured workflow body"
            )
        workflow, deficits = self.service.validate_duet_workflow(
            self.identity.duet_id,
            blueprint,
        )
        validation_error = (
            None
            if not deficits
            else "; ".join(
                item.detail or f"{item.field_path}: {item.code}"
                for item in deficits
            )
        )
        return {
            "revision": int(draft["revision"]),
            "ready": not deficits,
            "content_hash": draft["record"]["workflow_blueprint_hash"],
            "workflow_hash": (
                None if workflow is None else workflow.workflow_hash.value
            ),
            "configuration": json.loads(canonical_json(blueprint)),
            "fields": {},
            "source_artifact_id": draft["artifact_id"],
            "source_kind": draft["kind"],
            "source_stage": draft["record"]["source_stage"],
            "editable": duet["state"] != "sealed",
            "validation_deficits": [item.as_record() for item in deficits],
            "measured": False,
            "validation_error": validation_error,
        }

    @contextmanager
    def episode_workflow_edit_session(self):
        with self._draft_write_lock:
            snapshot = self.episode_workflow_configuration()
            if not snapshot["editable"]:
                raise DuetProtocolError(
                    "the approved Episode workflow is frozen and read-only"
                )
            yield snapshot

    def record_episode_workflow_revision(
        self,
        workflow_blueprint: Mapping[str, Any],
        *,
        source_artifact_id: str,
        expected_workflow_hash: str,
    ) -> dict[str, Any]:
        with self._draft_write_lock:
            current = self.episode_workflow_configuration()
            if (
                current["source_artifact_id"] != source_artifact_id
                or current["content_hash"] != expected_workflow_hash
            ):
                raise DuetProtocolError(
                    "Episode workflow changed or was superseded while it was edited"
                )
            artifact = self.service.record_duet_workflow_draft(
                duet_id=self.identity.duet_id,
                workflow_blueprint=workflow_blueprint,
                expected_workflow_hash=expected_workflow_hash,
                source_stage="human_edit",
            )
            return self._draft_receipt(artifact)

    def record_duet_workflow_revision(
        self,
        workflow_blueprint: Mapping[str, Any],
        *,
        expected_workflow_hash: Optional[str],
        source_stage: str = "duet",
    ) -> dict[str, Any]:
        with self._draft_write_lock:
            artifact = self.service.record_duet_workflow_draft(
                duet_id=self.identity.duet_id,
                workflow_blueprint=workflow_blueprint,
                expected_workflow_hash=expected_workflow_hash,
                source_stage=source_stage,
            )
            return self._draft_receipt(artifact)

    @staticmethod
    def _draft_receipt(artifact: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "revision": int(artifact["revision"]),
            "artifact_id": artifact["artifact_id"],
            "content_hash": artifact["content_hash"],
            "workflow_hash": artifact["record"].get("workflow_hash"),
            "ready": bool(artifact["record"].get("ready")),
            "validation_deficits": list(
                artifact["record"].get("validation_deficits") or ()
            ),
        }

    def approve_current(self) -> HumanActionReceipt:
        snapshot = self.episode_workflow_configuration()
        if not snapshot["ready"]:
            codes = [
                item.get("code", "invalid_workflow")
                for item in snapshot.get("validation_deficits") or ()
            ]
            raise DuetProtocolError(
                "Episode workflow still has blocking deterministic deficits: "
                + ", ".join(codes)
            )
        frozen = self.service.freeze_duet_workflow(
            duet_id=self.identity.duet_id,
            source_draft_artifact_id=OpaqueId(snapshot["source_artifact_id"]),
            source_draft_hash=Sha256Digest(snapshot["content_hash"]),
        )
        approval = self.service.record_human_approval(
            self.identity,
            kind=ApprovalKind.WORKFLOW,
            artifact_id=frozen.artifact_id,
            content_hash=frozen.workflow_hash,
            revision=frozen.revision,
        )
        return HumanActionReceipt(
            kind=ApprovalKind.WORKFLOW.value,
            artifact_id=frozen.artifact_id,
            approval_id=approval.approval_id,
        )

    def status(self) -> dict[str, Any]:
        status = self.service.duet_status(self.identity.duet_id)
        try:
            snapshot = self.episode_workflow_configuration()
        except DuetProtocolError:
            snapshot = None
        status["episode_workflow"] = (
            None
            if snapshot is None
            else {
                "artifact_id": snapshot["source_artifact_id"],
                "revision": snapshot["revision"],
                "workflow_blueprint_hash": snapshot["content_hash"],
                "workflow_hash": snapshot["workflow_hash"],
                "validation_state": (
                    "ready" if snapshot["ready"] else "invalid"
                ),
                "error_code": snapshot.get("validation_error"),
            }
        )
        return status

    def has_active_work(self) -> bool:
        return False

    def run_log_locations(self) -> tuple[str, ...]:
        root = self.root / "run_logs"
        if not root.is_dir():
            return ()
        return tuple(
            str(path)
            for path in sorted(
                root.glob("*/*.json"),
                key=lambda item: item.stat().st_mtime,
            )
        )


__all__ = [
    "HumanActionReceipt",
    "OpenChiaHost",
    "OpenChiaHostError",
]
