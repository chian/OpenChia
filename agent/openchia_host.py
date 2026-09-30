"""Concrete host for the interactive Duet-design -> approved workflow path.

The host owns persistence, human approvals, background execution, mechanical
measurement, and role-specific agent construction. The Duet model persists the
actual workflow; critics are explicit `/review` workers; the host validates,
freezes, and executes exactly the human-approved tree.
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
    RunLogReference,
    WorkflowCandidateDesign,
)
from agent.creator_runtime import (
    CreatorRuntime,
    CreatorRuntimeBindings,
    RunEvaluation,
)
from agent.duet_contracts import (
    ApprovalKind,
    CreatorActivityEnvelope,
    CreatorActivityStage,
    DUET_PROTOCOL_TOOLS,
    DUET_SEARCH_TOOLS,
    OPENCHIA_CONTROL_PLANE_TOOLS,
    DuetIdentity,
    DuetPolicy,
    FrozenDuetWorkflow,
    canonical_json,
    content_id,
)
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.duet_service import (
    DuetProtocolError,
    DuetService,
    EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
)
from agent.duet_store import DuetStore
from agent.episode_contracts import (
    ChildEpisodeStopReason,
    ChildEpisodeUpdate,
    EpisodeCreationSpec,
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
WORKFLOW_REVIEW_LENSES = frozenset(
    {
        "contract_alignment",
        "measurement_evidence",
        "iteration_recovery",
        "capability_safety",
        "task_specific_skeptic",
    }
)
logger = logging.getLogger(__name__)


class OpenChiaHostError(RuntimeError):
    """The concrete OpenChia execution host cannot honor a frozen contract."""


class _ApprovedWorkflowOutcomeError(RuntimeError):
    """The approved tree terminated cleanly without satisfying its root goal."""

    def __init__(
        self,
        update: ChildEpisodeUpdate,
        log: RunLogReference,
    ) -> None:
        self.update = update
        self.log = log
        super().__init__(
            "approved workflow stopped without reaching its goal: "
            f"{update.stop_reason.value} at progress {update.progress_value}"
        )


@dataclass(frozen=True)
class HumanActionReceipt:
    kind: str
    artifact_id: OpaqueId
    approval_id: OpaqueId
    launch_id: Optional[OpaqueId] = None


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
            self.identity = requested_identity
            self.policy = requested_policy
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
        blueprint = snapshot["configuration"]
        blueprint_hash = Sha256Digest.of_record(blueprint)
        authority = self.service.workflow_admission_authority(
            self.identity.duet_id
        )
        latest = self.store.latest_artifact(
            duet_id=self.identity.duet_id.value,
            kind="workflow_shadow_review",
            unowned_only=True,
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
        review_context_artifacts: dict[str, dict[str, Any]] = {}
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
                "admission_authority": authority.as_record(),
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

    def _role_agent_kwargs(self, role: str, identity: str) -> dict[str, Any]:
        """Resolve one role-specific model configuration from the CLI host."""

        kwargs = self.agent_kwargs_factory(role, identity)
        if not isinstance(kwargs, dict):
            raise TypeError("agent_kwargs_factory must return a dictionary")
        return kwargs

    def _creator_log_store(
        self,
        creator_episode_id: OpaqueId,
    ) -> CreatorRunLogStore:
        """Return the immutable log namespace for one explicit Creator node."""

        return CreatorRunLogStore(
            self.root / "run_logs" / creator_episode_id.value
        )

    def _workflow_log_store(self, launch_id: OpaqueId) -> CreatorRunLogStore:
        """Return the immutable log namespace for one directly approved Run."""

        return CreatorRunLogStore(self.root / "run_logs" / launch_id.value)

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
        *,
        duet_id: OpaqueId,
        design_artifact_id: OpaqueId,
        creator_episode_id: Optional[OpaqueId],
        episode_id: str,
        result: dict[str, Any],
    ) -> OpaqueId:
        record = {
            "episode_id": episode_id,
            "design_artifact_id": design_artifact_id.value,
            "producer_creator_episode_id": (
                None if creator_episode_id is None else creator_episode_id.value
            ),
            "result": result,
        }
        artifact_id = content_id("result", record)
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=duet_id.value,
            creator_episode_id=(
                None if creator_episode_id is None else creator_episode_id.value
            ),
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
        design: FrozenDuetWorkflow | WorkflowCandidateDesign,
        owner_creator_episode_id: Optional[OpaqueId],
        workflow_approval_id: Optional[OpaqueId] = None,
    ) -> WorkflowRuntime:
        def nested_creator(
            *,
            node: Any,
            goal: EpisodeGoal,
            runtime_key: str,
        ) -> Episode:
            if owner_creator_episode_id is None:
                if not isinstance(design, FrozenDuetWorkflow) or workflow_approval_id is None:
                    raise OpenChiaHostError(
                        "top-level Creator admission lacks workflow approval authority"
                    )
                nested_id = self.service.admit_workflow_creator(
                    frozen_workflow=design,
                    workflow_approval_id=workflow_approval_id,
                    node_local_id=node.local_id,
                )
            else:
                nested_id = self.service.admit_nested_creator(
                    parent_creator_episode_id=owner_creator_episode_id,
                    workflow_design_artifact_id=design.artifact_id,
                    node_local_id=node.local_id,
                )
            self._begin_creator_attempt(nested_id)
            runtime = self._creator_runtime(nested_id)
            return runtime.bind(
                goal=goal,
                nested=True,
                runtime_key=runtime_key,
            )

        return WorkflowRuntime(
            agent_factory=self._task_agent,
            result_sink=lambda *, episode_id, result: self._persist_task_result(
                duet_id=(
                    design.duet_id
                    if isinstance(design, FrozenDuetWorkflow)
                    else self.identity.duet_id
                ),
                design_artifact_id=design.artifact_id,
                creator_episode_id=owner_creator_episode_id,
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
            design=candidate,
            owner_creator_episode_id=creator_episode_id,
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
        design: FrozenDuetWorkflow,
        run_id: str,
        workflow_approval_id: OpaqueId,
        launch_id: OpaqueId,
    ) -> RunLogReference:
        """Build and execute exactly one human-approved workflow design."""

        workflow = self._workflow_runtime(
            design=design,
            owner_creator_episode_id=None,
            workflow_approval_id=workflow_approval_id,
        )
        run_grain = self.creator_bindings.run_grain
        goal = EpisodeGoal.root(
            objective={
                "kind": "execute_approved_workflow",
                "workflow_artifact_id": design.artifact_id.value,
            },
            result_contract={"kind": "typed_episode_result"},
        )
        source = workflow.source_for_candidate(design, goal)
        declared_depths = [
            item.contract.safety_bounds.max_depth
            for item in design.workflow.episodes
            if item.contract.safety_bounds is not None
        ]
        max_depth = max([8, *declared_depths])
        record = Episode(
            grain=run_grain,
            key=f"approved-{design.artifact_id.value[-12:]}",
            source=source,
            request=EpisodeRequest(goal=goal),
            bound=1,
        ).run(Context(tree=self._final_tree(max_depth), run_id=run_id))
        log = self._workflow_log_store(launch_id).persist(record)
        log_record = {
            "schema_version": 1,
            "launch_id": launch_id.value,
            "workflow_artifact_id": design.artifact_id.value,
            "workflow_hash": design.workflow_hash.value,
            "execution_run_id": run_id,
            "log": log.as_record(),
        }
        self.store.put_artifact(
            artifact_id=log.artifact_id.value,
            duet_id=design.duet_id.value,
            creator_episode_id=None,
            kind="workflow_run_log",
            revision=0,
            content_hash=log.digest.value,
            record=log_record,
        )
        update = self._root_update(record)
        if not update.goal_reached:
            raise _ApprovedWorkflowOutcomeError(update, log)
        return log

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
        design: FrozenDuetWorkflow,
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
            creator_episode_id=None,
            kind="workflow_execution_activity",
            revision=event_index,
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return record

    @staticmethod
    def _workflow_failure_record(
        *,
        design: FrozenDuetWorkflow,
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
        outcome_error = (
            exc if isinstance(exc, _ApprovedWorkflowOutcomeError) else None
        )
        record = {
            "schema_version": 1,
            "launch_id": launch_id.value,
            "workflow_artifact_id": design.artifact_id.value,
            "workflow_hash": design.workflow_hash.value,
            "failed_stage": "execute_approved_workflow",
            "error_code": (
                "workflow_goal_not_reached"
                if outcome_error is not None
                else type(exc).__name__
            ),
            "message": (str(exc).strip() or repr(exc))[:4096],
            "owner": "openchia_host" if host_error else "episode_execution",
            "design_change_required": False if host_error else None,
            "suggested_action": (
                "Fix the OpenChia runtime before relaunching the unchanged design."
                if host_error
                else "Inspect the failed Episode and its run log; edit the design only if the failure is contractual."
            ),
        }
        if outcome_error is not None:
            record["root_update"] = outcome_error.update.as_record()
            record["run_log"] = outcome_error.log.as_record()
        return record

    def _record_workflow_failure(
        self,
        *,
        design: FrozenDuetWorkflow,
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
            creator_episode_id=None,
            kind="workflow_execution_error",
            revision=record["failure_index"],
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return {"error_artifact_id": artifact_id.value, **record}

    def _run_frozen_workflow_tracked(
        self,
        design: FrozenDuetWorkflow,
        run_id: str,
        launch_id: OpaqueId,
        workflow_approval_id: OpaqueId,
    ) -> None:
        self._publish_workflow_activity(
            design=design,
            launch_id=launch_id,
            stage="constructing",
            activity_code="materializing_approved_episode_tree",
        )
        try:
            self.store.set_launch_status(launch_id.value, "running")
            log = self._run_frozen_workflow(
                design,
                run_id,
                workflow_approval_id,
                launch_id,
            )
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
            self.store.set_launch_status(launch_id.value, "failed")
        else:
            self._publish_workflow_activity(
                design=design,
                launch_id=launch_id,
                stage="completed",
                activity_code="approved_workflow_completed",
                details={
                    "run_log_artifact_id": log.artifact_id.value,
                    "run_log_digest": log.digest.value,
                },
            )
            with self._lock:
                self._final_completed.add(launch_id.value)
            self.store.set_launch_status(launch_id.value, "completed")

    def approve_current(self) -> HumanActionReceipt:
        """Freeze, approve, and launch the exact Duet-owned Episode workflow."""

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
        attempt = self.store.launch_count(
            duet_id=self.identity.duet_id.value,
            workflow_artifact_id=frozen.artifact_id.value,
        ) + 1
        run_id = content_id(
            "run",
            {
                "approved_workflow": frozen.artifact_id.value,
                "approval_id": approval.approval_id.value,
                "attempt": attempt,
            },
        ).value
        launch_id = self.service.launch_duet_workflow(
            frozen=frozen,
            workflow_approval_id=approval.approval_id,
            run_id=run_id,
        )
        with self._lock:
            self._final_errors.pop(launch_id.value, None)
            self._final_completed.discard(launch_id.value)
        self._publish_workflow_activity(
            design=frozen,
            launch_id=launch_id,
            stage="queued",
            activity_code="approved_workflow_queued",
        )
        thread = threading.Thread(
            target=self._run_frozen_workflow_tracked,
            args=(frozen, run_id, launch_id, approval.approval_id),
            name=f"openchia-workflow-{launch_id.value[-12:]}",
            daemon=True,
        )
        with self._lock:
            self._final_threads[launch_id.value] = thread
            thread.start()
        return HumanActionReceipt(
            kind=ApprovalKind.WORKFLOW.value,
            artifact_id=frozen.artifact_id,
            approval_id=approval.approval_id,
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
            persisted_launch_state = str(launch.get("status") or "")
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
                elif persisted_launch_state in {
                    "queued",
                    "running",
                    "failed",
                    "completed",
                }:
                    final_state = persisted_launch_state
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
    "HumanActionReceipt",
    "OpenChiaHost",
    "OpenChiaHostError",
    "ROOT_PROGRESS_MEASUREMENT_ID",
    "RUN_EVIDENCE_ACCEPTANCE_SOURCE_ID",
]
