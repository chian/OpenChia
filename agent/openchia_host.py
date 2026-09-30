"""Concrete host for the interactive Duet-design -> Creator/build -> Run path.

The host owns persistence, human approvals, background execution, mechanical
measurement, and role-specific agent construction. The Duet model persists the
actual workflow; critics are explicit `/review` workers; the internal root
Creator builds only the human-approved tree.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Optional

from agent.creator_design_session import CreatorDesignSession
from agent.creator_episode import (
    CreatorRunLogStore,
    RunEpisodeStopReason,
    WorkflowCandidateDesign,
)
from agent.creator_runtime import (
    CreatorRuntime,
    CreatorRuntimeBindings,
    RunEvaluation,
)
from agent.duet_contracts import (
    ApprovalKind,
    ContractFieldRecord,
    CreatorActivityEnvelope,
    CreatorActivityStage,
    DUET_PROTOCOL_TOOLS,
    DUET_SEARCH_TOOLS,
    OPENCHIA_CONTROL_PLANE_TOOLS,
    DuetAnswer,
    DuetDesignState,
    DuetIdentity,
    DuetPolicy,
    DuetProvenance,
    FrozenWorkflowDesign,
    canonical_json,
    content_id,
)
from agent.episode_blueprints import (
    CREATION_BLUEPRINT_FIELDS,
    workflow_blueprint_from_spec,
)
from agent.duet_service import (
    DuetProtocolError,
    DuetService,
    EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
    WorkflowAdmissionError,
)
from agent.duet_store import DuetStore
from agent.episode_contracts import (
    ChildEpisodeStopReason,
    ChildEpisodeUpdate,
    EpisodeCreationSpec,
    EpisodeCreatorContext,
    EpisodeEvidenceMeasurement,
    EpisodeMeasuredOutcome,
    MAX_CREATOR_CONTEXT_TOTAL_BYTES,
    OpaqueId,
    ProgressDirection,
    Sha256Digest,
)
from agent.interrupt_compat import request_hard_interrupt
from agent.openchia_agents import (
    bind_duet_agent,
    build_creator_agent,
    build_creator_workflow_critic_agent,
    build_task_episode_agent,
)
from agent.task_episode import TaskRuntimeBindings
from agent.workflow_runtime import WorkflowRuntime
from method_loop import Context, Episode, EpisodeGoal, EpisodeRequest, EpisodeTree


ROOT_PROGRESS_MEASUREMENT_ID = "root_episode_progress"
RUN_EVIDENCE_ACCEPTANCE_SOURCE_ID = "run_episode_host"
EPISODE_FIELD_PLACEHOLDER = "<OPENCHIA: value required>"
WORKFLOW_REVIEW_LENSES = frozenset(
    {
        "contract_alignment",
        "measurement_evidence",
        "iteration_recovery",
        "capability_safety",
        "task_specific_skeptic",
    }
)
_RETIRED_DUET_PROTOCOL_TOOLS = frozenset(
    {"duet_contract_review", "episode_creator"}
)

logger = logging.getLogger(__name__)


class OpenChiaHostError(RuntimeError):
    """The concrete OpenChia execution host cannot honor a frozen contract."""


@dataclass(frozen=True)
class HumanActionReceipt:
    kind: str
    artifact_id: OpaqueId
    approval_id: OpaqueId
    launch_id: Optional[OpaqueId] = None


class OpenChiaHost:
    """Persistent authority and execution host for one interactive Duet."""

    @staticmethod
    def _migrate_retired_duet_policy(
        store: DuetStore,
        existing: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Replace the removed review/launch surface in one persisted policy."""

        raw_identity = existing.get("identity")
        raw_policy = existing.get("policy")
        if not isinstance(raw_identity, Mapping) or not isinstance(
            raw_policy,
            Mapping,
        ):
            raise OpenChiaHostError("stored Duet authority has an invalid shape")
        if set(raw_policy) != {
            "policy_id",
            "capability_allowlist",
            "minimum_method_credit",
            "creator_proposal_bound",
            "maximum_creator_depth",
        }:
            raise OpenChiaHostError("stored Duet policy has an invalid shape")
        stored_identity = DuetIdentity.from_record(raw_identity)
        if raw_policy.get("policy_id") != stored_identity.policy_id.value:
            raise OpenChiaHostError(
                "stored Duet identity and policy IDs differ"
            )
        raw_allowlist = raw_policy.get("capability_allowlist")
        if not isinstance(raw_allowlist, list) or any(
            not isinstance(name, str) or not name for name in raw_allowlist
        ):
            raise OpenChiaHostError(
                "stored Duet capability allowlist has an invalid shape"
            )
        retired = set(raw_allowlist) & _RETIRED_DUET_PROTOCOL_TOOLS
        if not retired:
            return dict(existing)
        unknown = set(raw_allowlist) - (
            DUET_PROTOCOL_TOOLS
            | DUET_SEARCH_TOOLS
            | _RETIRED_DUET_PROTOCOL_TOOLS
        )
        if unknown:
            raise OpenChiaHostError(
                "stored Duet policy contains unknown capabilities and cannot be "
                f"migrated safely: {sorted(unknown)}"
            )
        replacement_capabilities = {"episode_workflow_update"}
        added = replacement_capabilities - set(raw_allowlist)
        migrated_allowlist = (
            set(raw_allowlist) - _RETIRED_DUET_PROTOCOL_TOOLS
        ) | replacement_capabilities
        policy_fields = {
            "capability_allowlist": sorted(migrated_allowlist),
            "minimum_method_credit": raw_policy.get("minimum_method_credit"),
            "creator_proposal_bound": raw_policy.get("creator_proposal_bound"),
            "maximum_creator_depth": raw_policy.get("maximum_creator_depth"),
        }
        migrated_policy_id = content_id("policy", policy_fields)
        migrated_policy = DuetPolicy(
            policy_id=migrated_policy_id,
            capability_allowlist=tuple(policy_fields["capability_allowlist"]),
            minimum_method_credit=policy_fields["minimum_method_credit"],
            creator_proposal_bound=policy_fields["creator_proposal_bound"],
            maximum_creator_depth=policy_fields["maximum_creator_depth"],
        )
        migrated_identity = DuetIdentity.from_record({
            **dict(raw_identity),
            "policy_id": migrated_policy_id.value,
        })
        store.migrate_duet_policy(
            duet_id=existing["duet_id"],
            expected_identity=raw_identity,
            expected_policy=raw_policy,
            identity=migrated_identity.as_record(),
            policy=migrated_policy.as_record(),
            migration_record={
                "schema_version": 1,
                "old_policy_id": raw_policy.get("policy_id"),
                "new_policy_id": migrated_policy_id.value,
                "removed_capability_names": sorted(retired),
                "added_capability_names": sorted(added),
                "authority_change": "retired_protocol_replacement",
            },
        )
        migrated = store.get_duet(existing["duet_id"])
        if migrated is None:
            raise OpenChiaHostError("migrated Duet disappeared from its store")
        return migrated

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
            if (
                isinstance(name, str)
                and name
                and name not in OPENCHIA_CONTROL_PLANE_TOOLS
            )
        )
        self.agent_kwargs_factory = agent_kwargs_factory
        duet_tools = DUET_PROTOCOL_TOOLS | (
            DUET_SEARCH_TOOLS & self.available_tool_names
        )
        policy_fields = {
            "capability_allowlist": sorted(duet_tools),
            "minimum_method_credit": 0.0,
            "creator_proposal_bound": 8,
            "maximum_creator_depth": 4,
        }
        policy_id = content_id("policy", policy_fields)
        requested_policy = DuetPolicy(
            policy_id=policy_id,
            capability_allowlist=tuple(policy_fields["capability_allowlist"]),
            minimum_method_credit=policy_fields["minimum_method_credit"],
            creator_proposal_bound=policy_fields["creator_proposal_bound"],
            maximum_creator_depth=policy_fields["maximum_creator_depth"],
        )
        requested_identity = DuetIdentity(
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
            existing = self.store.get_duet(requested_identity.duet_id.value)
            if existing is None:
                self.identity = requested_identity
                self.policy = requested_policy
            else:
                existing = self._migrate_retired_duet_policy(
                    self.store,
                    existing,
                )
                self.identity = DuetIdentity.from_record(existing["identity"])
                self.policy = DuetPolicy.from_record(existing["policy"])
                expected_authority = (
                    requested_identity.duet_id,
                    requested_identity.human_authority_id,
                    requested_identity.conversation_id,
                )
                stored_authority = (
                    self.identity.duet_id,
                    self.identity.human_authority_id,
                    self.identity.conversation_id,
                )
                if stored_authority != expected_authority:
                    raise OpenChiaHostError(
                        "the resumed Duet ID belongs to different immutable authority"
                    )
                if self.identity.policy_id != self.policy.policy_id:
                    raise OpenChiaHostError(
                        "the resumed Duet identity and policy IDs differ"
                    )
                unavailable = set(self.policy.capability_allowlist) - duet_tools
                if unavailable:
                    raise OpenChiaHostError(
                        "the resumed Duet requires unavailable capabilities: "
                        f"{sorted(unavailable)}"
                    )
            self.service.open_duet(self.identity, self.policy)
        except Exception:
            self.store.close()
            raise
        self.creator_bindings = CreatorRuntimeBindings()
        self.task_bindings = TaskRuntimeBindings()
        self._lock = threading.RLock()
        self._draft_write_lock = threading.RLock()
        self._creator_attempts: dict[str, int] = {}
        self._creator_activity_indexes: dict[str, int] = {}
        self._creator_attempt_started_at: dict[str, float] = {}
        self._final_threads: dict[str, threading.Thread] = {}
        self._final_errors: dict[str, dict[str, Any]] = {}
        self._final_completed: set[str] = set()
        self._workflow_activity_indexes: dict[str, int] = {}
        self._duet_agent: Any = None

    def close(self) -> None:
        self.store.close()

    @staticmethod
    def _names_from_agent(agent: Any) -> tuple[str, ...]:
        names = getattr(agent, "valid_tool_names", ())
        return tuple(sorted(name for name in names if isinstance(name, str)))

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
        """Run an auxiliary critic inside its parent's hard-stop fan-out."""

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
                raise ValueError("shadow critic did not return a JSON object")
            value = json.loads(text[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("shadow critic response must be a JSON object")
        verdict = value.get("verdict")
        if verdict not in {"pass", "concern", "block"}:
            raise ValueError("shadow critic verdict is invalid")
        summary = value.get("summary")
        findings = value.get("findings")
        if not isinstance(summary, str) or not isinstance(findings, list):
            raise ValueError("shadow critic response is missing summary or findings")
        normalized = []
        for finding in findings[:12]:
            if not isinstance(finding, dict):
                raise ValueError("shadow critic findings must be objects")
            code = finding.get("code")
            severity = finding.get("severity")
            fields = finding.get("fields")
            explanation = finding.get("explanation")
            question = finding.get("question")
            if (
                not isinstance(code, str)
                or severity not in {"low", "medium", "high"}
                or not isinstance(fields, list)
                or any(not isinstance(item, str) for item in fields)
                or not isinstance(explanation, str)
                or not isinstance(question, str)
            ):
                raise ValueError("shadow critic finding has an invalid shape")
            normalized.append(
                {
                    "code": code[:128],
                    "severity": severity,
                    "fields": fields[:9],
                    "explanation": explanation[:2048],
                    "question": question[:2048],
                }
            )
        return {
            "verdict": verdict,
            "summary": summary[:4096],
            "findings": normalized,
        }

    def review_episode_design(self) -> dict[str, Any]:
        """Run the opt-in critic fan-out for the exact Duet-owned workflow.

        This is called only by the trusted ``/review`` command. Neither the
        Duet model nor an internal Creator has a tool that reaches this method.
        """

        snapshot = self.episode_workflow_configuration()
        if not snapshot["ready"]:
            raise DuetProtocolError(
                "design review requires a deterministically valid Episode workflow"
            )
        draft = self.service.latest_draft(self.identity.duet_id)
        blueprint = snapshot["configuration"]
        blueprint_hash = Sha256Digest.of_record(blueprint)
        latest = self.store.latest_artifact(
            duet_id=self.identity.duet_id.value,
            kind="workflow_shadow_review",
            unowned_only=True,
        )
        if (
            latest is not None
            and latest["record"].get("workflow_blueprint_hash")
            == blueprint_hash.value
            and latest["record"].get("creator_contract_hash")
            == draft.content_hash.value
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
        materialized = draft.materialized()
        creator_record = materialized.get("creator_contract")
        review_context_artifacts: dict[str, dict[str, Any]] = {}
        if isinstance(creator_record, Mapping):
            review_context_artifacts.update(
                self.service.resolve_creator_context(
                    self.identity.duet_id,
                    EpisodeCreatorContext.from_record(
                        creator_record["design_context"]
                    ),
                )
            )
        for node in workflow.episodes:
            child_contract = node.contract.creator_contract
            if child_contract is not None:
                review_context_artifacts.update(
                    self.service.resolve_creator_context(
                        self.identity.duet_id,
                        child_contract.design_context,
                    )
                )
        if (
            len(canonical_json(review_context_artifacts).encode("utf-8"))
            > MAX_CREATOR_CONTEXT_TOTAL_BYTES
        ):
            raise DuetProtocolError(
                "design review context exceeds the exact-delivery budget"
            )

        lenses = tuple(sorted(WORKFLOW_REVIEW_LENSES))

        def review_lens(lens: str) -> tuple[str, dict[str, Any]]:
            critic = build_creator_workflow_critic_agent(
                **self._role_agent_kwargs(
                    "workflow_critic",
                    f"{blueprint_hash.value}:{lens}",
                )
            )
            request = {
                "operation": "review_duet_episode_design",
                "lens": lens,
                "creator_contract_hash": draft.content_hash.value,
                "creator_contract": materialized,
                "creator_context_artifacts": review_context_artifacts,
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

        with ThreadPoolExecutor(
            max_workers=len(lenses),
            thread_name_prefix="openchia-explicit-review",
        ) as pool:
            reviews = dict(pool.map(review_lens, lenses))
        record = {
            "creator_episode_id": None,
            "creator_contract_hash": draft.content_hash.value,
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

    def record_episode_workflow_draft(
        self,
        creator_episode_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
        source_stage: str,
        *,
        consumed_context_artifact_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Durably append the exact Episode workflow crossing a design boundary."""

        return self.service.record_episode_workflow_draft(
            creator_episode_id=creator_episode_id,
            workflow_blueprint=workflow_blueprint,
            source_stage=source_stage,
            consumed_context_artifact_ids=consumed_context_artifact_ids,
        )

    def episode_configuration(self) -> dict[str, Any]:
        """Return the editable Creator draft plus validation and provenance."""

        draft = self.service.latest_draft(self.identity.duet_id)
        return {
            "revision": draft.revision,
            "ready": draft.ready,
            "content_hash": draft.content_hash.value,
            "deficits": [item.as_record() for item in draft.deficits],
            "configuration": draft.materialized(),
            "fields": {
                item.field_path: {
                    "provenance": item.provenance.value,
                    "approved": item.approved,
                    "validation_codes": list(item.validation_codes),
                }
                for item in draft.fields
            },
            "allowed_capabilities": sorted(self.available_tool_names),
        }

    def episode_workflow_configuration(self) -> dict[str, Any]:
        """Return the newest Duet-owned nested Episode workflow draft."""

        draft = self.store.latest_artifact(
            duet_id=self.identity.duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
            unowned_only=True,
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
        normalized_workflow_hash = (
            None if workflow is None else workflow.workflow_hash.value
        )
        return {
            "revision": int(draft["revision"]),
            "ready": not deficits,
            "content_hash": draft["record"]["workflow_blueprint_hash"],
            "workflow_hash": normalized_workflow_hash,
            "configuration": json.loads(canonical_json(blueprint)),
            "fields": {},
            "source_artifact_id": draft["artifact_id"],
            "source_kind": draft["kind"],
            "source_stage": draft["record"]["source_stage"],
            "editable": True,
            "validation_deficits": [item.as_record() for item in deficits],
            "measured": False,
            "validation_error": validation_error,
        }

    @contextmanager
    def episode_workflow_edit_session(self):
        """Open a frozen workflow for a structured human revision."""

        with self._draft_write_lock:
            self._assert_revision_write_safe()
            snapshot = self.episode_workflow_configuration()
            if not snapshot["editable"]:
                raise DuetProtocolError(
                    "this Episode draft was invalidated by changed design constraints; "
                    "wait for the current design pass to produce a replacement"
                )
            yield snapshot

    def record_episode_workflow_revision(
        self,
        workflow_blueprint: Mapping[str, Any],
        *,
        source_artifact_id: str,
        expected_workflow_hash: str,
    ) -> dict[str, Any]:
        """Persist an exact human edit and run deterministic validation only."""

        with self._draft_write_lock:
            self._assert_revision_write_safe()
            current = self.episode_workflow_configuration()
            if (
                not current["editable"]
                or current["source_artifact_id"] != source_artifact_id
                or current["content_hash"] != expected_workflow_hash
            ):
                raise DuetProtocolError(
                    "Episode workflow changed or was superseded while it was edited"
                )
            source = self.store.get_artifact(source_artifact_id)
            if (
                source is None
                or source["kind"] != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
                or source["creator_episode_id"] is not None
            ):
                raise DuetProtocolError("Episode workflow source artifact is missing")
            artifact = self.service.record_duet_workflow_draft(
                duet_id=self.identity.duet_id,
                workflow_blueprint=workflow_blueprint,
                expected_workflow_hash=expected_workflow_hash,
                source_stage="human_edit",
            )
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

    def record_duet_workflow_revision(
        self,
        workflow_blueprint: Mapping[str, Any],
        *,
        expected_workflow_hash: Optional[str],
        source_stage: str = "duet",
    ) -> dict[str, Any]:
        """Persist one model-proposed workflow revision behind a hash guard."""

        with self._draft_write_lock:
            self._assert_revision_write_safe()
            artifact = self.service.record_duet_workflow_draft(
                duet_id=self.identity.duet_id,
                workflow_blueprint=workflow_blueprint,
                expected_workflow_hash=expected_workflow_hash,
                source_stage=source_stage,
            )
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

    def episode_editor_document(self) -> tuple[int, dict[str, Any]]:
        """Build a complete top-level document suitable for direct editing."""

        draft = self.service.latest_draft(self.identity.duet_id)
        current = draft.materialized()
        return draft.revision, {
            field: current.get(field, EPISODE_FIELD_PLACEHOLDER)
            for field in CREATION_BLUEPRINT_FIELDS
        }

    def episode_has_creator_history(self) -> bool:
        """Return whether Save must cross a fresh approval boundary."""

        return self.store.latest_creator(self.identity.duet_id.value) is not None

    @contextmanager
    def episode_edit_session(self):
        """Give the human exclusive draft-write ownership for one editor session.

        An admitted contract is immutable, but it is not the mutable draft.  A
        later human edit creates a new revision whose exact hash must be
        approved and admitted independently.
        """

        with self._draft_write_lock:
            self._assert_revision_write_safe()
            yield self.episode_editor_document()

    def record_human_answer(self, field_path: str, value: Any) -> DuetAnswer:
        """Record one exact answer through the trusted human host boundary."""

        self._assert_revision_write_safe()
        requests = {
            request.field_path: request
            for request in self.service.information_requests(self.identity.duet_id)
        }
        request = requests.get(field_path)
        if request is None:
            available = ", ".join(sorted(requests)) or "none"
            raise DuetProtocolError(
                f"{field_path} is not an open information request; open fields: "
                f"{available}"
            )
        return self.service.record_human_answer(
            self.identity,
            request_id=request.request_id,
            value=value,
        )

    def _assert_revision_write_safe(self) -> None:
        """Reject only concurrent writes, never a revision after terminal work."""

        with self._lock:
            workflow_running = any(
                thread.is_alive() for thread in self._final_threads.values()
            )
        if workflow_running:
            raise DuetProtocolError(
                "Episode configuration cannot be revised while execution is running"
            )

    def _configuration_with_revision_context(
        self,
        configuration: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Attach exact recovery inputs when revising an admitted contract."""

        normalized = json.loads(canonical_json(configuration))
        creator = self.store.latest_creator(self.identity.duet_id.value)
        if creator is None:
            return normalized

        contract_artifact = self.store.get_artifact(creator["contract_artifact_id"])
        if contract_artifact is None:
            raise OpenChiaHostError("the prior Creator contract artifact is missing")

        creator_contract = normalized.get("creator_contract")
        if not isinstance(creator_contract, dict):
            return normalized

        configured_context = creator_contract.get("design_context")
        existing_context: Optional[EpisodeCreatorContext] = None
        try:
            existing_context = EpisodeCreatorContext.from_record(configured_context)
            self.service.resolve_creator_context(
                self.identity.duet_id,
                existing_context,
            )
        except (TypeError, ValueError, DuetProtocolError):
            existing_context = None

        brief_contract = dict(creator_contract)
        brief_contract.pop("design_context", None)
        # Supplemental design instructions are context, not executable
        # authority.  Preserve them exactly in the task brief instead of
        # admitting an unknown control-plane field.
        creator_contract.pop("design_instructions", None)
        brief = self.service.register_creator_context_artifact(
            self.identity.duet_id,
            artifact_kind="task_design_brief",
            schema_version=1,
            purpose="revision_entrypoint",
            required=True,
            provenance=DuetProvenance.HOST_VALIDATION,
            content={
                "schema_version": 1,
                "source_draft_revision": expected_revision,
                "superseded_creator_episode_id": creator["creator_episode_id"],
                "configuration": {
                    **normalized,
                    "creator_contract": brief_contract,
                },
            },
        )
        prior_contract = self.service.register_creator_context_artifact(
            self.identity.duet_id,
            artifact_kind="creator_contract_history",
            schema_version=1,
            purpose="prior_contract",
            required=True,
            provenance=DuetProvenance.HOST_VALIDATION,
            content={
                "source_artifact_id": contract_artifact["artifact_id"],
                "source_content_hash": contract_artifact["content_hash"],
                "record": contract_artifact["record"],
            },
        )
        recovery_references = [brief, prior_contract]
        for kind, artifact_kind, purpose in (
            ("creator_execution_error", "creator_failure_history", "prior_failure"),
        ):
            artifact = self.store.latest_artifact(
                duet_id=self.identity.duet_id.value,
                kind=kind,
                creator_episode_id=creator["creator_episode_id"],
            )
            if artifact is None:
                continue
            recovery_references.append(
                self.service.register_creator_context_artifact(
                    self.identity.duet_id,
                    artifact_kind=artifact_kind,
                    schema_version=1,
                    purpose=purpose,
                    required=True,
                    provenance=DuetProvenance.HOST_VALIDATION,
                    content={
                        "source_artifact_id": artifact["artifact_id"],
                        "source_content_hash": artifact["content_hash"],
                        "record": artifact["record"],
                    },
                )
            )

        references = []
        entrypoint_id = brief.artifact_id
        if existing_context is not None:
            revision_artifact_kinds = {
                "task_design_brief",
                "creator_contract_history",
                "creator_failure_history",
            }
            preserved_references = tuple(
                reference
                for reference in existing_context.artifact_references
                if reference.artifact_kind not in revision_artifact_kinds
            )
            references.extend(preserved_references)
            if existing_context.entrypoint_artifact_id in {
                reference.artifact_id for reference in preserved_references
            }:
                entrypoint_id = existing_context.entrypoint_artifact_id
        references.extend(recovery_references)
        references_by_id = {
            reference.artifact_id.value: reference for reference in references
        }
        creator_contract["design_context"] = EpisodeCreatorContext(
            entrypoint_artifact_id=entrypoint_id,
            artifact_references=tuple(references_by_id.values()),
            unresolved_question_ids=(
                ()
                if existing_context is None
                else existing_context.unresolved_question_ids
            ),
        ).as_record()
        return normalized

    def replace_episode_configuration(
        self,
        configuration: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Replace the draft exactly with a directly edited human configuration."""

        with self._draft_write_lock:
            self._assert_revision_write_safe()
            if not isinstance(configuration, Mapping):
                raise TypeError("Episode configuration must be a JSON object")
            unknown = sorted(set(configuration) - set(CREATION_BLUEPRINT_FIELDS))
            if unknown:
                raise ValueError(f"unknown Episode configuration fields: {unknown}")
            configuration = self._configuration_with_revision_context(
                configuration,
                expected_revision=expected_revision,
            )
            fields = tuple(
                ContractFieldRecord(
                    field_path=field,
                    value=value,
                    provenance=DuetProvenance.HUMAN_INPUT,
                    approved=True,
                )
                for field in CREATION_BLUEPRINT_FIELDS
                if (value := configuration.get(field, EPISODE_FIELD_PLACEHOLDER))
                != EPISODE_FIELD_PLACEHOLDER
            )
            draft = self.service.replace_contract(
                self.identity.duet_id,
                expected_revision=expected_revision,
                fields=fields,
            )
            return draft.as_record()

    def update_episode_configuration(
        self,
        field_path: str,
        *,
        value: Any = None,
        remove: bool = False,
    ) -> dict[str, Any]:
        """Set or remove one dotted path, committing one human-authored revision."""

        with self._draft_write_lock:
            if not isinstance(field_path, str) or not field_path.strip():
                raise ValueError("field path must be non-empty")
            parts = field_path.strip().split(".")
            if parts[0] not in CREATION_BLUEPRINT_FIELDS:
                raise ValueError(f"unknown Episode configuration field: {parts[0]}")
            revision, document = self.episode_editor_document()
            current = {
                key: item
                for key, item in document.items()
                if item != EPISODE_FIELD_PLACEHOLDER
            }
            if len(parts) == 1:
                if remove:
                    if parts[0] not in current:
                        raise KeyError(f"Episode field is not set: {field_path}")
                    del current[parts[0]]
                else:
                    current[parts[0]] = value
            else:
                root = current.get(parts[0])
                if root is None and not remove:
                    root = {}
                    current[parts[0]] = root
                if not isinstance(root, dict):
                    raise ValueError(
                        f"Episode field {parts[0]} is not an object; replace it first"
                    )
                cursor = root
                for part in parts[1:-1]:
                    child = cursor.get(part)
                    if child is None and not remove:
                        child = {}
                        cursor[part] = child
                    if not isinstance(child, dict):
                        raise ValueError(f"Episode path is not an object: {part}")
                    cursor = child
                leaf = parts[-1]
                if remove:
                    if leaf not in cursor:
                        raise KeyError(f"Episode field is not set: {field_path}")
                    del cursor[leaf]
                else:
                    cursor[leaf] = value
            return self.replace_episode_configuration(
                current,
                expected_revision=revision,
            )

    def _role_agent_kwargs(self, role: str, identity: str) -> dict[str, Any]:
        kwargs = self.agent_kwargs_factory(role, identity)
        if not isinstance(kwargs, dict):
            raise TypeError("agent_kwargs_factory must return a dictionary")
        return kwargs

    def _creator_log_store(self, creator_episode_id: OpaqueId) -> CreatorRunLogStore:
        return CreatorRunLogStore(
            self.root / "run_logs" / creator_episode_id.value
        )

    def _validate_host_measurement_contract(
        self,
        spec: EpisodeCreationSpec,
    ) -> None:
        contract = spec.creator_contract
        if contract is None:
            raise OpenChiaHostError("Creator Episode has no Creator contract")
        if contract.required_existing_evidence_ids:
            raise OpenChiaHostError(
                "the interactive host does not seed pre-existing evaluation evidence"
            )
        if contract.return_contract.measurement_ids != (
            ROOT_PROGRESS_MEASUREMENT_ID,
        ):
            raise OpenChiaHostError(
                "the interactive host supports the root_episode_progress "
                "measurement only"
            )
        for requirement in contract.evidence_requirements:
            if (
                requirement.acceptance_source_id
                != RUN_EVIDENCE_ACCEPTANCE_SOURCE_ID
                or requirement.minimum_count != 1
            ):
                raise OpenChiaHostError(
                    "Creator evidence must require one run_episode_host observation"
                )
        for component in contract.credit_assignment.components:
            if (
                component.measurement_id != ROOT_PROGRESS_MEASUREMENT_ID
                or component.direction is not ProgressDirection.INCREASE
                or component.normalization_baseline != 0.0
                or component.normalization_target != 1.0
            ):
                raise OpenChiaHostError(
                    "Creator credit must normalize root_episode_progress from 0 to 1"
                )

    @staticmethod
    def _root_update(record: Any) -> ChildEpisodeUpdate:
        if len(record.unit_records) != 1:
            raise OpenChiaHostError("a Run Episode must execute exactly one workflow root")
        unit = record.unit_records[0]
        update = None if unit.episode_update is None else unit.episode_update.controller_input
        if not isinstance(update, ChildEpisodeUpdate):
            raise OpenChiaHostError("workflow root returned no typed child update")
        return update

    @staticmethod
    def _progress_fraction(
        root_spec: EpisodeCreationSpec,
        update: ChildEpisodeUpdate,
    ) -> float:
        baseline = root_spec.progress.baseline
        target = root_spec.stopping.target
        if target == baseline:
            return 1.0 if update.goal_reached else 0.0
        if root_spec.progress.direction is ProgressDirection.INCREASE:
            value = (update.progress_value - baseline) / (target - baseline)
        else:
            value = (baseline - update.progress_value) / (baseline - target)
        return min(1.0, max(0.0, float(value)))

    @staticmethod
    def _run_stop_reason(update: ChildEpisodeUpdate) -> RunEpisodeStopReason:
        mapping = {
            ChildEpisodeStopReason.TARGET_REACHED: RunEpisodeStopReason.TARGET_REACHED,
            ChildEpisodeStopReason.NO_PROGRESS: RunEpisodeStopReason.NO_PROGRESS,
            ChildEpisodeStopReason.SAFETY_BOUND: RunEpisodeStopReason.BOUND_HIT,
            ChildEpisodeStopReason.SOURCE_EXHAUSTED: RunEpisodeStopReason.SOURCE_EXHAUSTED,
            ChildEpisodeStopReason.DELIVERABLE_MISSING: RunEpisodeStopReason.VALIDATION_FAILED,
            ChildEpisodeStopReason.ERROR: RunEpisodeStopReason.ERROR,
            ChildEpisodeStopReason.CANCELLED: RunEpisodeStopReason.CANCELLED,
            ChildEpisodeStopReason.NONE: RunEpisodeStopReason.SOURCE_EXHAUSTED,
        }
        return mapping[update.stop_reason]

    def _run_evaluator(
        self,
        creator_episode_id: OpaqueId,
        candidate: WorkflowCandidateDesign,
        record: Any,
        log: Any,
    ) -> RunEvaluation:
        frozen = self.service.creator_contract(creator_episode_id)
        contract = frozen.contract.creator_contract
        if contract is None:
            raise OpenChiaHostError("Creator contract disappeared during evaluation")
        update = self._root_update(record)
        root = next(
            item
            for item in candidate.workflow.episodes
            if item.workflow_parent_local_id is None
        )
        fraction = self._progress_fraction(root.contract, update)
        evidence_by_requirement: dict[str, OpaqueId] = {}
        for requirement in contract.evidence_requirements:
            evidence_by_requirement[requirement.requirement_id] = (
                self.service.register_evidence(
                    duet_id=frozen.duet_id,
                    creator_episode_id=creator_episode_id,
                    evidence_kind_id=requirement.evidence_kind_id,
                    acceptance_source_id=requirement.acceptance_source_id,
                    observation={
                        "candidate_artifact_id": candidate.artifact_id.value,
                        "run_episode_id": record.episode_id,
                        "run_log_artifact_id": log.artifact_id.value,
                        "root_update": update.as_record(),
                    },
                    source_artifact_id=candidate.artifact_id,
                )
            )
        required_ids = {
            requirement_id
            for component in contract.credit_assignment.components
            if component.measurement_id == ROOT_PROGRESS_MEASUREMENT_ID
            for requirement_id in component.evidence_requirement_ids
        }
        measurement = EpisodeMeasuredOutcome(
            measurement_id=ROOT_PROGRESS_MEASUREMENT_ID,
            value=fraction,
            evidence=tuple(
                EpisodeEvidenceMeasurement(
                    requirement_id=requirement_id,
                    accepted_evidence_ids=(evidence_by_requirement[requirement_id],),
                )
                for requirement_id in sorted(required_ids)
            ),
        )
        evidence_ids = tuple(
            evidence_by_requirement[key]
            for key in sorted(evidence_by_requirement)
        )
        return RunEvaluation(
            goal_reached=update.goal_reached,
            stop_reason=self._run_stop_reason(update),
            goal_result_ids=update.accepted_result_ids,
            accepted_evidence_ids=evidence_ids,
            measured_outcomes=(measurement,),
        )

    def _persist_task_result(
        self,
        creator_episode_id: OpaqueId,
        *,
        episode_id: str,
        result: dict[str, Any],
    ) -> OpaqueId:
        frozen = self.service.creator_contract(creator_episode_id)
        record = {
            "episode_id": episode_id,
            "creator_episode_id": creator_episode_id.value,
            "result": result,
        }
        artifact_id = content_id("result", record)
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=frozen.duet_id.value,
            creator_episode_id=creator_episode_id.value,
            kind="task_result",
            revision=0,
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return artifact_id

    def _task_agent(
        self,
        *,
        spec: EpisodeCreationSpec,
        episode_id: str,
        accepted_evidence_ids: tuple[OpaqueId, ...],
    ) -> Any:
        return build_task_episode_agent(
            capability_names=spec.execution_capability_names,
            episode_id=episode_id,
            accepted_evidence_ids=(item.value for item in accepted_evidence_ids),
            **self._role_agent_kwargs("task_episode", episode_id),
        )

    def _workflow_runtime(
        self,
        *,
        creator_episode_id: OpaqueId,
        candidate: WorkflowCandidateDesign,
    ) -> WorkflowRuntime:
        def nested_creator(*, node: Any, goal: EpisodeGoal) -> Episode:
            nested_id = self.service.admit_nested_creator(
                parent_creator_episode_id=creator_episode_id,
                workflow_design_artifact_id=candidate.artifact_id,
                node_local_id=node.local_id,
            )
            self._begin_creator_attempt(nested_id)
            runtime = self._creator_runtime(nested_id)
            return runtime.bind(goal=goal, nested=True)

        return WorkflowRuntime(
            agent_factory=self._task_agent,
            result_sink=lambda *, episode_id, result: self._persist_task_result(
                creator_episode_id,
                episode_id=episode_id,
                result=result,
            ),
            creator_node_builder=nested_creator,
            bindings=self.task_bindings,
        )

    def _begin_creator_attempt(self, creator_episode_id: OpaqueId) -> int:
        """Reserve a new durable attempt number and activity sequence."""

        creator_key = creator_episode_id.value
        latest = self.store.latest_artifact(
            duet_id=self.service.creator_contract(creator_episode_id).duet_id.value,
            kind="creator_activity",
            creator_episode_id=creator_key,
        )
        last_attempt = 0
        last_event_index = 0
        if latest is not None:
            last_attempt = int(latest["record"]["attempt"])
            last_event_index = int(latest["record"]["event_index"])
        with self._lock:
            attempt = max(
                last_attempt,
                self._creator_attempts.get(creator_key, 0),
            ) + 1
            self._creator_attempts[creator_key] = attempt
            self._creator_activity_indexes[creator_key] = last_event_index
            self._creator_attempt_started_at[creator_key] = time.time()
        return attempt

    def _publish_creator_activity(
        self,
        creator_episode_id: OpaqueId,
        stage: CreatorActivityStage | str,
        activity_code: str,
        details: Mapping[str, Any],
    ) -> OpaqueId:
        """Publish a typed live stage event for the active Creator attempt."""

        if isinstance(stage, str):
            stage = CreatorActivityStage(stage)
        creator_key = creator_episode_id.value
        with self._lock:
            attempt = self._creator_attempts.get(creator_key)
            if attempt is None:
                attempt = 1
                self._creator_attempts[creator_key] = attempt
                self._creator_activity_indexes.setdefault(creator_key, 0)
                self._creator_attempt_started_at.setdefault(
                    creator_key,
                    time.time(),
                )
            event_index = self._creator_activity_indexes.get(creator_key, 0) + 1
            self._creator_activity_indexes[creator_key] = event_index
            attempt_started_at = self._creator_attempt_started_at[creator_key]
        return self.service.publish_creator_activity(
            CreatorActivityEnvelope(
                creator_episode_id=creator_episode_id,
                attempt=attempt,
                event_index=event_index,
                stage=stage,
                activity_code=activity_code,
                attempt_started_at=attempt_started_at,
                observed_at=time.time(),
                details=details,
            )
        )

    def _candidate_run_source(
        self,
        creator_episode_id: OpaqueId,
        candidate: WorkflowCandidateDesign,
        run_goal: EpisodeGoal,
    ) -> Any:
        self._publish_creator_activity(
            creator_episode_id,
            CreatorActivityStage.RUNNING_CANDIDATE,
            "candidate_run_started",
            {
                "candidate_artifact_id": candidate.artifact_id.value,
                "candidate_revision": candidate.revision,
            },
        )
        return self._workflow_runtime(
            creator_episode_id=creator_episode_id,
            candidate=candidate,
        ).source_for_candidate(candidate, run_goal)

    def _evaluate_candidate_run(
        self,
        creator_episode_id: OpaqueId,
        candidate: WorkflowCandidateDesign,
        record: Any,
        log: Any,
    ) -> RunEvaluation:
        self._publish_creator_activity(
            creator_episode_id,
            CreatorActivityStage.EVALUATING,
            "candidate_run_evaluating",
            {
                "candidate_artifact_id": candidate.artifact_id.value,
                "candidate_revision": candidate.revision,
                "run_episode_id": record.episode_id,
            },
        )
        return self._run_evaluator(
            creator_episode_id,
            candidate,
            record,
            log,
        )

    def _creator_runtime(self, creator_episode_id: OpaqueId) -> CreatorRuntime:
        frozen = self.service.creator_contract(creator_episode_id)
        self._validate_host_measurement_contract(frozen.contract)
        logs = self._creator_log_store(creator_episode_id)
        context_artifacts = self.service.creator_context_artifacts(
            creator_episode_id
        )
        creator_capabilities = tuple(
            sorted(DUET_SEARCH_TOOLS & self.available_tool_names)
        )
        agent_slot: dict[str, Any] = {}
        agent = build_creator_agent(
            capability_names=creator_capabilities,
            log_store=logs,
            workflow_draft_recorder=lambda workflow, stage: (
                self.record_episode_workflow_draft(
                    creator_episode_id,
                    workflow,
                    stage,
                    consumed_context_artifact_ids=tuple(
                        sorted(
                            getattr(
                                agent_slot.get("agent"),
                                "_creator_context_read_ids",
                                set(),
                            )
                        )
                    ),
                )
            ),
            context_service=self.service,
            creator_episode_id=creator_episode_id,
            context_artifacts=context_artifacts,
            creation_spec=frozen.contract,
            **self._role_agent_kwargs("creator", creator_episode_id.value),
        )
        agent_slot["agent"] = agent
        agent._creator_activity_publisher = (
            lambda stage, activity_code, details: self._publish_creator_activity(
                creator_episode_id,
                stage,
                activity_code,
                details,
            )
        )
        designer = CreatorDesignSession(
            service=self.service,
            creator_episode_id=creator_episode_id,
            agent=agent,
            activity_publisher=agent._creator_activity_publisher,
        )
        return CreatorRuntime(
            service=self.service,
            creator_episode_id=creator_episode_id,
            designer=designer,
            log_store=logs,
            run_source_factory=lambda candidate, run_goal: self._candidate_run_source(
                creator_episode_id,
                candidate,
                run_goal,
            ),
            run_evaluator=lambda candidate, record, log: self._evaluate_candidate_run(
                creator_episode_id,
                candidate,
                record,
                log,
            ),
            bindings=self.creator_bindings,
        )

    def _final_tree(self, max_depth: int) -> EpisodeTree:
        creator = self.creator_bindings.creator_grain
        run = self.creator_bindings.run_grain
        task = self.task_bindings.grain
        return EpisodeTree(
            root=run,
            children={
                run: (task, creator),
                task: (task, creator),
                creator: (run,),
            },
            self_nesting=(task.name,),
            recursive_edges=(
                (run.name, task.name),
                (run.name, creator.name),
                (task.name, creator.name),
                (creator.name, run.name),
            ),
            max_depth=max_depth,
        )

    def _run_frozen_workflow(
        self,
        design: FrozenWorkflowDesign,
        run_id: str,
        approved_artifact_id: OpaqueId,
    ) -> None:
        """Build and execute exactly one human-approved workflow design."""

        creator_id = design.creator_episode_id
        workflow = self._workflow_runtime(
            creator_episode_id=creator_id,
            candidate=design,
        )
        run_grain = self.creator_bindings.run_grain
        goal = EpisodeGoal.root(
            objective={
                "kind": "execute_approved_workflow",
                "workflow_artifact_id": approved_artifact_id.value,
            },
            result_contract={"kind": "typed_episode_result"},
        )
        source = workflow.source_for_candidate(design, goal)
        root_spec = self.service.creator_contract(creator_id).contract
        bounds = root_spec.safety_bounds
        max_depth = 8 if bounds is None else bounds.max_depth
        Episode(
            grain=run_grain,
            key=f"approved-{design.artifact_id.value[-12:]}",
            source=source,
            request=EpisodeRequest(goal=goal),
            bound=1,
        ).run(Context(tree=self._final_tree(max_depth), run_id=run_id))

    def _workflow_events(
        self,
        launch_id: OpaqueId | str,
    ) -> tuple[dict[str, Any], ...]:
        launch_value = launch_id.value if isinstance(launch_id, OpaqueId) else launch_id
        return tuple(
            artifact
            for artifact in self.store.artifacts_by_kind(
                duet_id=self.identity.duet_id.value,
                kind="workflow_execution_activity",
            )
            if artifact["record"].get("launch_id") == launch_value
        )

    def _publish_workflow_activity(
        self,
        *,
        design: FrozenWorkflowDesign,
        launch_id: OpaqueId,
        stage: str,
        activity_code: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        with self._lock:
            previous = self._workflow_activity_indexes.get(launch_id.value)
            if previous is None:
                previous = max(
                    (
                        int(item["record"].get("event_index") or 0)
                        for item in self._workflow_events(launch_id)
                    ),
                    default=0,
                )
            event_index = previous + 1
            self._workflow_activity_indexes[launch_id.value] = event_index
        record = {
            "schema_version": 1,
            "launch_id": launch_id.value,
            "workflow_artifact_id": design.artifact_id.value,
            "workflow_hash": design.workflow_hash.value,
            "event_index": event_index,
            "stage": stage,
            "activity_code": activity_code,
            "details": dict(details or {}),
        }
        artifact_id = content_id("activity", record)
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=self.identity.duet_id.value,
            creator_episode_id=design.creator_episode_id.value,
            kind="workflow_execution_activity",
            revision=event_index,
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return record

    @staticmethod
    def _workflow_failure_record(
        *,
        design: FrozenWorkflowDesign,
        launch_id: OpaqueId,
        exc: Exception,
    ) -> dict[str, Any]:
        host_error = isinstance(
            exc,
            (
                OpenChiaHostError,
                NameError,
                AttributeError,
                TypeError,
                AssertionError,
            ),
        )
        return {
            "schema_version": 1,
            "launch_id": launch_id.value,
            "workflow_artifact_id": design.artifact_id.value,
            "workflow_hash": design.workflow_hash.value,
            "failed_stage": "execute_approved_workflow",
            "error_code": type(exc).__name__,
            "message": (str(exc).strip() or repr(exc))[:4096],
            "owner": "openchia_host" if host_error else "episode_execution",
            "design_change_required": False if host_error else None,
            "suggested_action": (
                "Fix the OpenChia runtime before relaunching the unchanged design."
                if host_error
                else "Inspect the failed Episode and its run log; edit the design only if the failure is contractual."
            ),
        }

    def _record_workflow_failure(
        self,
        *,
        design: FrozenWorkflowDesign,
        launch_id: OpaqueId,
        exc: Exception,
    ) -> dict[str, Any]:
        record = self._workflow_failure_record(
            design=design,
            launch_id=launch_id,
            exc=exc,
        )
        prior_failures = tuple(
            artifact
            for artifact in self.store.artifacts_by_kind(
                duet_id=self.identity.duet_id.value,
                kind="workflow_execution_error",
            )
            if artifact["record"].get("launch_id") == launch_id.value
        )
        record["failure_index"] = len(prior_failures) + 1
        artifact_id = content_id("runerror", record)
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=self.identity.duet_id.value,
            creator_episode_id=design.creator_episode_id.value,
            kind="workflow_execution_error",
            revision=record["failure_index"],
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return {"error_artifact_id": artifact_id.value, **record}

    def _run_frozen_workflow_tracked(
        self,
        design: FrozenWorkflowDesign,
        run_id: str,
        launch_id: OpaqueId,
    ) -> None:
        self._publish_workflow_activity(
            design=design,
            launch_id=launch_id,
            stage="constructing",
            activity_code="materializing_approved_episode_tree",
        )
        try:
            self._run_frozen_workflow(design, run_id, design.artifact_id)
        except Exception as exc:
            logger.exception(
                "Approved Episode workflow failed: artifact_id=%s",
                design.artifact_id.value,
            )
            failure = self._record_workflow_failure(
                design=design,
                launch_id=launch_id,
                exc=exc,
            )
            self._publish_workflow_activity(
                design=design,
                launch_id=launch_id,
                stage="failed",
                activity_code="approved_workflow_failed",
                details={
                    "error_artifact_id": failure["error_artifact_id"],
                    "error_code": failure["error_code"],
                    "owner": failure["owner"],
                },
            )
            with self._lock:
                self._final_errors[launch_id.value] = failure
        else:
            self._publish_workflow_activity(
                design=design,
                launch_id=launch_id,
                stage="completed",
                activity_code="approved_workflow_completed",
            )
            with self._lock:
                self._final_completed.add(launch_id.value)

    def approve_current(self) -> HumanActionReceipt:
        """Approve, build, and launch the exact Duet-designed Episode tree."""

        workflow_snapshot = self.episode_workflow_configuration()
        if not workflow_snapshot["ready"]:
            codes = [
                item.get("code", "invalid_workflow")
                for item in workflow_snapshot.get("validation_deficits") or ()
            ]
            raise DuetProtocolError(
                "Episode workflow still has blocking deterministic deficits: "
                + ", ".join(codes)
            )
        draft = self.service.latest_draft(self.identity.duet_id)
        if not draft.ready:
            raise DuetProtocolError(
                "internal build authority still has blocking deficits"
            )
        frozen = self.service.freeze_creator_contract(
            self.identity.duet_id,
            expected_revision=draft.revision,
        )
        self._validate_host_measurement_contract(frozen.contract)
        approval = self.service.record_human_approval(
            self.identity,
            kind=ApprovalKind.CREATOR_CONTRACT,
            artifact_id=frozen.artifact_id,
            content_hash=frozen.content_hash,
            revision=frozen.revision,
        )
        creator_id = self.service.submit_episode_creator(
            contract_artifact_id=frozen.artifact_id,
            content_hash=frozen.content_hash,
            human_approval_id=approval.approval_id,
        )
        creator_contract = frozen.contract.creator_contract
        if creator_contract is None:
            raise OpenChiaHostError("internal build authority is missing")
        context_receipts = tuple(
            reference.artifact_id.value
            for reference in creator_contract.design_context.artifact_references
        )
        design = self.service.freeze_workflow_design(
            creator_episode_id=creator_id,
            workflow_blueprint=workflow_snapshot["configuration"],
            consumed_context_artifact_ids=context_receipts,
            source_stage="frozen",
            identity_namespace=f"{self.identity.duet_id.value}:duet-workflow",
        )
        workflow_approval = self.service.record_human_approval(
            self.identity,
            kind=ApprovalKind.WORKFLOW,
            artifact_id=design.artifact_id,
            content_hash=design.workflow_hash,
            revision=design.revision,
        )
        run_id = content_id(
            "run",
            {"approved_workflow": design.artifact_id.value},
        ).value
        launch_id = self.service.launch_workflow(
            workflow_artifact_id=design.artifact_id,
            workflow_hash=design.workflow_hash,
            workflow_approval_id=workflow_approval.approval_id,
            run_id=run_id,
        )
        with self._lock:
            self._final_errors.pop(launch_id.value, None)
            self._final_completed.discard(launch_id.value)
        self._publish_workflow_activity(
            design=design,
            launch_id=launch_id,
            stage="queued",
            activity_code="approved_workflow_queued",
        )
        thread = threading.Thread(
            target=self._run_frozen_workflow_tracked,
            args=(design, run_id, launch_id),
            name=f"openchia-workflow-{design.artifact_id.value[-12:]}",
            daemon=True,
        )
        with self._lock:
            self._final_threads[launch_id.value] = thread
            thread.start()
        return HumanActionReceipt(
            kind=ApprovalKind.WORKFLOW.value,
            artifact_id=design.artifact_id,
            approval_id=workflow_approval.approval_id,
            launch_id=launch_id,
        )

    def status(self) -> dict[str, Any]:
        status = self.service.duet_status(self.identity.duet_id)
        try:
            workflow_snapshot = self.episode_workflow_configuration()
        except DuetProtocolError:
            workflow_snapshot = None
        if workflow_snapshot is not None:
            source_id = workflow_snapshot["source_artifact_id"]
            validation_error = workflow_snapshot.get("validation_error")
            validation_state = (
                "ready" if workflow_snapshot["ready"] else "invalid"
            )
            status["episode_workflow"] = {
                "artifact_id": source_id,
                "revision": workflow_snapshot["revision"],
                "workflow_blueprint_hash": workflow_snapshot["content_hash"],
                "workflow_hash": workflow_snapshot["workflow_hash"],
                "validation_state": validation_state,
                "error_code": validation_error,
            }
        else:
            status["episode_workflow"] = None
        launch = status.get("launch") or {}
        launch_id = launch.get("launch_id")
        if launch_id:
            event_artifacts = self._workflow_events(launch_id)
            activity_history = [item["record"] for item in event_artifacts[-8:]]
            activity = activity_history[-1] if activity_history else None
            failure_artifacts = tuple(
                item
                for item in self.store.artifacts_by_kind(
                    duet_id=self.identity.duet_id.value,
                    kind="workflow_execution_error",
                )
                if item["record"].get("launch_id") == launch_id
            )
            persisted_failure = (
                None
                if not failure_artifacts
                else {
                    "error_artifact_id": failure_artifacts[-1]["artifact_id"],
                    **failure_artifacts[-1]["record"],
                }
            )
            with self._lock:
                final = self._final_threads.get(launch_id)
                if final is not None and final.is_alive():
                    final_state = "running"
                elif activity is not None and activity.get("stage") == "completed":
                    final_state = "completed"
                elif activity is not None and activity.get("stage") == "failed":
                    final_state = "failed"
                elif launch_id in self._final_errors:
                    final_state = "failed"
                elif launch_id in self._final_completed:
                    final_state = "completed"
                else:
                    final_state = "persisted_launch"
                failure = self._final_errors.get(launch_id) or persisted_failure
                status["final_run_state"] = final_state
                status["final_error_code"] = (
                    None if final_state != "failed" or failure is None
                    else failure.get("error_code")
                )
                status["workflow_execution"] = {
                    "state": final_state,
                    "current_activity": activity,
                    "activity_history": activity_history,
                    "failure": (
                        failure if final_state == "failed" else None
                    ),
                }
        else:
            status["final_run_state"] = "idle"
            status["final_error_code"] = None
            status["workflow_execution"] = None
        return status

    def has_active_work(self) -> bool:
        """Return whether a Creator experiment or approved workflow is running."""

        with self._lock:
            return (
                any(thread.is_alive() for thread in self._final_threads.values())
            )

    def run_log_locations(self) -> tuple[str, ...]:
        root = self.root / "run_logs"
        if not root.is_dir():
            return ()
        return tuple(
            str(path)
            for path in sorted(root.glob("*/*.json"), key=lambda item: item.stat().st_mtime)
        )


__all__ = [
    "EPISODE_FIELD_PLACEHOLDER",
    "HumanActionReceipt",
    "OpenChiaHost",
    "OpenChiaHostError",
    "ROOT_PROGRESS_MEASUREMENT_ID",
    "RUN_EVIDENCE_ACCEPTANCE_SOURCE_ID",
]
