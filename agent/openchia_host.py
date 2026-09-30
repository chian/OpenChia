"""Concrete host for the interactive Duet -> Creator -> Run product path.

The host owns persistence, human approvals, background execution, mechanical
measurement, and role-specific agent construction.  Models may propose typed
contracts and workflows; they never approve themselves, select their own tool
surface, compute their own credit, or send Run prose into the Duet.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import threading
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
    CreatorLaunchReceipt,
    CreatorLaunchState,
    CreatorProgressEnvelope,
    DUET_PROTOCOL_TOOLS,
    DUET_SEARCH_TOOLS,
    OPENCHIA_CONTROL_PLANE_TOOLS,
    DuetAnswer,
    DuetDesignState,
    DuetIdentity,
    DuetMessageKind,
    DuetPolicy,
    DuetProvenance,
    WorkflowCandidate,
    canonical_json,
    content_id,
)
from agent.episode_blueprints import (
    CREATION_BLUEPRINT_FIELDS,
    workflow_spec_from_blueprint,
)
from agent.duet_service import DuetProtocolError, DuetService
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
    build_duet_contract_critic_agent,
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
        policy_id = OpaqueId.mint("policy", "openchia-interactive-v1")
        self.identity = DuetIdentity(
            duet_id=OpaqueId.mint("duet", session_id),
            human_authority_id=OpaqueId.mint("human", f"local:{self.root}"),
            policy_id=policy_id,
            conversation_id=OpaqueId.mint("conversation", session_id),
        )
        duet_tools = DUET_PROTOCOL_TOOLS | (
            DUET_SEARCH_TOOLS & self.available_tool_names
        )
        self.policy = DuetPolicy(
            policy_id=policy_id,
            capability_allowlist=tuple(sorted(duet_tools)),
            minimum_method_credit=0.0,
            creator_proposal_bound=8,
            maximum_creator_depth=4,
        )
        self.service = DuetService(
            self.store,
            allowed_episode_capabilities=self.available_tool_names,
        )
        self.service.open_duet(self.identity, self.policy)
        self.creator_bindings = CreatorRuntimeBindings()
        self.task_bindings = TaskRuntimeBindings()
        self._lock = threading.RLock()
        self._draft_write_lock = threading.RLock()
        self._creator_threads: dict[str, threading.Thread] = {}
        self._final_threads: dict[str, threading.Thread] = {}
        self._execution_errors: dict[str, str] = {}
        self._final_errors: dict[str, str] = {}
        self._final_completed: set[str] = set()
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
            creator_launcher=self.launch_creator,
        )
        bound._duet_contract_reviewer = self.review_contract
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

    def review_contract(self) -> dict[str, Any]:
        """Run or reuse the advisory critic for the exact current draft hash."""

        draft = self.service.latest_draft(self.identity.duet_id)
        if not draft.ready:
            raise DuetProtocolError("shadow review requires a complete valid contract")
        latest = self.store.latest_artifact(
            duet_id=self.identity.duet_id.value,
            kind="contract_shadow_review",
        )
        if latest is not None and latest["record"].get("contract_hash") == draft.content_hash.value:
            return {"accepted": True, "cached": True, **latest["record"]}
        critic = build_duet_contract_critic_agent(
            **self._role_agent_kwargs("contract_critic", draft.content_hash.value)
        )
        materialized = draft.materialized()
        creator_record = materialized.get("creator_contract")
        context_artifacts: dict[str, dict[str, Any]] = {}
        if isinstance(creator_record, Mapping):
            context_artifacts = self.service.resolve_creator_context(
                self.identity.duet_id,
                EpisodeCreatorContext.from_record(
                    creator_record["design_context"]
                ),
            )
        request = {
            "operation": "review_creator_contract",
            "contract_hash": draft.content_hash.value,
            "contract": materialized,
            "creator_context_artifacts": context_artifacts,
            "allowed_episode_capability_names": sorted(self.available_tool_names),
            "host_facts": {
                "root_measurement_id": ROOT_PROGRESS_MEASUREMENT_ID,
                "run_evidence_acceptance_source_id": RUN_EVIDENCE_ACCEPTANCE_SOURCE_ID,
            },
        }
        review = self._parse_contract_review(
            self._chat_as_interruptible_child(
                self._duet_agent,
                critic,
                canonical_json(request),
            )
        )
        record = {
            "contract_hash": draft.content_hash.value,
            "revision": draft.revision,
            **review,
        }
        artifact_id = content_id("review", record)
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=self.identity.duet_id.value,
            kind="contract_shadow_review",
            revision=draft.revision,
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return {
            "accepted": True,
            "cached": False,
            "review_artifact_id": artifact_id.value,
            **record,
        }

    def review_workflow_blueprint(
        self,
        creator_episode_id: OpaqueId,
        workflow_blueprint: dict[str, Any],
        lenses: tuple[str, ...],
        *,
        parent_agent: Any = None,
    ) -> dict[str, Any]:
        """Run independent advisory lenses before a Creator freezes a candidate."""

        if not lenses or len(set(lenses)) != len(lenses):
            raise ValueError("workflow review lenses must be non-empty and unique")
        unknown = set(lenses) - WORKFLOW_REVIEW_LENSES
        if unknown:
            raise ValueError(f"unknown workflow review lenses: {sorted(unknown)}")
        frozen = self.service.creator_contract(creator_episode_id)
        blueprint_hash = Sha256Digest.of_record(workflow_blueprint)
        workflow = workflow_spec_from_blueprint(
            workflow_blueprint,
            identity_namespace=(
                f"workflow-review:{creator_episode_id.value}:{blueprint_hash.value}"
            ),
        )
        deficits = self.service.workflow_deficits(
            creator_episode_id=creator_episode_id,
            workflow=workflow,
        )
        if deficits:
            return {
                "accepted": False,
                "reason": "workflow_admission_failed",
                "deficits": [item.as_record() for item in deficits],
            }
        review_context_artifacts = self.service.creator_context_artifacts(
            creator_episode_id
        )
        for node in workflow.episodes:
            creator_contract = node.contract.creator_contract
            if creator_contract is None:
                continue
            review_context_artifacts.update(
                self.service.resolve_creator_context(
                    frozen.duet_id,
                    creator_contract.design_context,
                    consumer_creator_episode_id=creator_episode_id,
                )
            )
        if (
            len(canonical_json(review_context_artifacts).encode("utf-8"))
            > MAX_CREATOR_CONTEXT_TOTAL_BYTES
        ):
            return {
                "accepted": False,
                "reason": "context_budget_exceeded",
                "deficits": [
                    {
                        "code": "context_budget_exceeded",
                        "field_path": "creator_contract.design_context",
                        "blocking": True,
                    }
                ],
            }

        def review_lens(lens: str) -> tuple[str, dict[str, Any]]:
            critic = build_creator_workflow_critic_agent(
                **self._role_agent_kwargs(
                    "workflow_critic",
                    f"{creator_episode_id.value}:{blueprint_hash.value}:{lens}",
                )
            )
            request = {
                "operation": "review_workflow_blueprint",
                "lens": lens,
                "creator_contract_hash": frozen.content_hash.value,
                "creator_contract": frozen.contract.as_record(),
                "creator_context_artifacts": review_context_artifacts,
                "workflow_blueprint_hash": blueprint_hash.value,
                "workflow": workflow_blueprint,
                "host_validation": {"admission_deficits": []},
            }
            return lens, self._parse_contract_review(
                self._chat_as_interruptible_child(
                    parent_agent,
                    critic,
                    canonical_json(request),
                )
            )

        with ThreadPoolExecutor(
            max_workers=min(len(lenses), 5),
            thread_name_prefix="openchia-workflow-critic",
        ) as pool:
            reviews = dict(pool.map(review_lens, lenses))
        record = {
            "creator_episode_id": creator_episode_id.value,
            "creator_contract_hash": frozen.content_hash.value,
            "workflow_blueprint_hash": blueprint_hash.value,
            "lenses": reviews,
        }
        artifact_id = content_id("review", record)
        creator = self.store.get_creator(creator_episode_id.value)
        revision = 0 if creator is None else int(creator["units_consumed"])
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=frozen.duet_id.value,
            creator_episode_id=creator_episode_id.value,
            kind="workflow_shadow_review",
            revision=revision,
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        return {
            "accepted": True,
            "review_artifact_id": artifact_id.value,
            **record,
        }

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

    def episode_editor_document(self) -> tuple[int, dict[str, Any]]:
        """Build a complete top-level document suitable for direct editing."""

        draft = self.service.latest_draft(self.identity.duet_id)
        current = draft.materialized()
        return draft.revision, {
            field: current.get(field, EPISODE_FIELD_PLACEHOLDER)
            for field in CREATION_BLUEPRINT_FIELDS
        }

    @contextmanager
    def episode_edit_session(self):
        """Give the human exclusive draft-write ownership for one editor session."""

        with self._draft_write_lock:
            self._assert_draft_mutable()
            yield self.episode_editor_document()

    def record_human_answer(self, field_path: str, value: Any) -> DuetAnswer:
        """Record one exact answer through the trusted human host boundary."""

        self._assert_draft_mutable()
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

    def _assert_draft_mutable(self) -> None:
        if self.service.duet_status(self.identity.duet_id).get("creator_episode_id"):
            raise DuetProtocolError(
                "the Creator contract is frozen and admitted; begin a new Duet to change it"
            )

    def replace_episode_configuration(
        self,
        configuration: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Replace the draft exactly with a directly edited human configuration."""

        with self._draft_write_lock:
            self._assert_draft_mutable()
            if not isinstance(configuration, Mapping):
                raise TypeError("Episode configuration must be a JSON object")
            unknown = sorted(set(configuration) - set(CREATION_BLUEPRINT_FIELDS))
            if unknown:
                raise ValueError(f"unknown Episode configuration fields: {unknown}")
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
            workflow_reviewer=lambda workflow, lenses: self.review_workflow_blueprint(
                creator_episode_id,
                workflow,
                lenses,
                parent_agent=agent_slot.get("agent"),
            ),
            context_service=self.service,
            creator_episode_id=creator_episode_id,
            context_artifacts=context_artifacts,
            creation_spec=frozen.contract,
            **self._role_agent_kwargs("creator", creator_episode_id.value),
        )
        agent_slot["agent"] = agent
        designer = CreatorDesignSession(
            service=self.service,
            creator_episode_id=creator_episode_id,
            agent=agent,
        )
        return CreatorRuntime(
            service=self.service,
            creator_episode_id=creator_episode_id,
            designer=designer,
            log_store=logs,
            run_source_factory=lambda candidate, run_goal: self._workflow_runtime(
                creator_episode_id=creator_episode_id,
                candidate=candidate,
            ).source_for_candidate(candidate, run_goal),
            run_evaluator=lambda candidate, record, log: self._run_evaluator(
                creator_episode_id,
                candidate,
                record,
                log,
            ),
            bindings=self.creator_bindings,
        )

    @staticmethod
    def _creator_goal(spec: EpisodeCreationSpec) -> EpisodeGoal:
        return EpisodeGoal.root(
            objective={"kind": "design_episode_workflow", "goal": spec.goal},
            result_contract={
                "kind": "measured_workflow_candidate",
                "measurement_id": ROOT_PROGRESS_MEASUREMENT_ID,
                "requires": ["run_log", "goal_information", "host_method_credit"],
            },
        )

    def _record_execution_error(
        self,
        creator_episode_id: OpaqueId,
        exc: BaseException,
    ) -> None:
        code = type(exc).__name__
        with self._lock:
            self._execution_errors[creator_episode_id.value] = code
        creator = self.store.get_creator(creator_episode_id.value)
        if creator is None:
            return
        sequence = int(creator["units_consumed"])
        self.service.publish_creator_progress(
            CreatorProgressEnvelope(
                creator_episode_id=creator_episode_id,
                sequence=sequence,
                state=DuetDesignState.FAILED,
                candidate_revision=0,
                deficit_count=1,
                validation_codes=("runtime_error",),
                accepted_evidence_ids=(),
                method_credit=None,
            )
        )
        record = {
            "creator_episode_id": creator_episode_id.value,
            "error_class": code,
            "message": str(exc),
        }
        artifact_id = content_id("error", record)
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=creator["duet_id"],
            creator_episode_id=creator_episode_id.value,
            kind="creator_execution_error",
            revision=sequence,
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )

    def _run_creator(self, creator_episode_id: OpaqueId, execution_id: OpaqueId) -> None:
        try:
            runtime = self._creator_runtime(creator_episode_id)
            bounds = runtime.frozen_contract.contract.safety_bounds
            max_depth = 8 if bounds is None else bounds.max_depth
            runtime.run(
                goal=self._creator_goal(runtime.frozen_contract.contract),
                run_id=execution_id.value,
                task_grain=self.task_bindings.grain,
                max_depth=max_depth,
            )
        except Exception as exc:
            self._record_execution_error(creator_episode_id, exc)

    def launch_creator(self, creator_episode_id: OpaqueId) -> CreatorLaunchReceipt:
        if not isinstance(creator_episode_id, OpaqueId):
            raise TypeError("creator_episode_id must be an OpaqueId")
        execution_id = content_id(
            "execution",
            {"creator_episode_id": creator_episode_id.value},
        )
        with self._lock:
            existing = self._creator_threads.get(creator_episode_id.value)
            if existing is not None:
                state = (
                    CreatorLaunchState.RUNNING
                    if existing.is_alive()
                    else CreatorLaunchState.COMPLETED
                )
                return CreatorLaunchReceipt(creator_episode_id, execution_id, state)
            thread = threading.Thread(
                target=self._run_creator,
                args=(creator_episode_id, execution_id),
                name=f"openchia-creator-{creator_episode_id.value[-12:]}",
                daemon=True,
            )
            self._creator_threads[creator_episode_id.value] = thread
            thread.start()
        return CreatorLaunchReceipt(
            creator_episode_id=creator_episode_id,
            execution_id=execution_id,
            state=CreatorLaunchState.LAUNCHED,
        )

    def _candidate_design(self, candidate: WorkflowCandidate) -> WorkflowCandidateDesign:
        design = self.store.latest_artifact(
            duet_id=candidate.duet_id.value,
            kind="workflow_design",
            creator_episode_id=candidate.creator_episode_id.value,
        )
        if (
            design is None
            or design["revision"] != candidate.revision
            or design["content_hash"] != candidate.workflow_hash.value
        ):
            raise OpenChiaHostError(
                "the measured workflow has no matching frozen design artifact"
            )
        return WorkflowCandidateDesign(
            revision=candidate.revision,
            artifact_id=OpaqueId(design["artifact_id"]),
            workflow=candidate.workflow,
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

    def _run_final_workflow(
        self,
        candidate: WorkflowCandidate,
        run_id: str,
    ) -> None:
        creator_id = candidate.creator_episode_id
        design = self._candidate_design(candidate)
        workflow = self._workflow_runtime(
            creator_episode_id=creator_id,
            candidate=design,
        )
        run_grain = self.creator_bindings.run_grain
        goal = EpisodeGoal.root(
            objective={
                "kind": "execute_approved_workflow",
                "workflow_artifact_id": candidate.artifact_id.value,
            },
            result_contract={"kind": "typed_episode_result"},
        )
        source = workflow.source_for_candidate(design, goal)
        root_spec = self.service.creator_contract(creator_id).contract
        bounds = root_spec.safety_bounds
        max_depth = 8 if bounds is None else bounds.max_depth
        Episode(
            grain=run_grain,
            key=f"approved-{candidate.artifact_id.value[-12:]}",
            source=source,
            request=EpisodeRequest(goal=goal),
            bound=1,
        ).run(Context(tree=self._final_tree(max_depth), run_id=run_id))

    def _run_final_workflow_tracked(
        self,
        candidate: WorkflowCandidate,
        run_id: str,
        launch_id: OpaqueId,
    ) -> None:
        try:
            self._run_final_workflow(candidate, run_id)
        except Exception as exc:
            with self._lock:
                self._final_errors[launch_id.value] = type(exc).__name__
        else:
            with self._lock:
                self._final_completed.add(launch_id.value)

    def approve_current(self) -> HumanActionReceipt:
        status = self.service.duet_status(self.identity.duet_id)
        if status["state"] == DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value:
            creator_id = OpaqueId(status["creator_episode_id"])
            candidate = self.service.latest_workflow_candidate(creator_id)
            approval = self.service.approve_workflow(self.identity, candidate).approval
            run_id = content_id(
                "run",
                {"approved_workflow": candidate.artifact_id.value},
            ).value
            launch_id = self.service.launch_workflow(
                workflow_artifact_id=candidate.artifact_id,
                workflow_hash=candidate.workflow_hash,
                workflow_approval_id=approval.approval_id,
                run_id=run_id,
            )
            thread = threading.Thread(
                target=self._run_final_workflow_tracked,
                args=(candidate, run_id, launch_id),
                name=f"openchia-workflow-{candidate.artifact_id.value[-12:]}",
                daemon=True,
            )
            with self._lock:
                self._final_threads[launch_id.value] = thread
                thread.start()
            return HumanActionReceipt(
                kind=ApprovalKind.WORKFLOW.value,
                artifact_id=candidate.artifact_id,
                approval_id=approval.approval_id,
                launch_id=launch_id,
            )

        draft = self.service.latest_draft(self.identity.duet_id)
        if not draft.ready:
            raise DuetProtocolError("Creator contract still has blocking deficits")
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
        return HumanActionReceipt(
            kind=ApprovalKind.CREATOR_CONTRACT.value,
            artifact_id=frozen.artifact_id,
            approval_id=approval.approval_id,
        )

    def _current_creator_boundary(self) -> tuple[OpaqueId, int]:
        status = self.service.duet_status(self.identity.duet_id)
        creator = status.get("creator_episode_id")
        if not creator:
            raise DuetProtocolError("this Duet has no admitted Creator Episode")
        progress = status.get("creator_progress") or {}
        return OpaqueId(creator), int(progress.get("sequence", 0))

    def guide_creator(self, instruction: str) -> OpaqueId:
        creator_id, sequence = self._current_creator_boundary()
        guidance = self.service.record_creator_guidance(
            self.identity,
            creator_episode_id=creator_id,
            expected_unit_index=sequence,
            instruction=instruction,
        )
        decision = self.service.record_human_decision(
            self.identity,
            creator_episode_id=creator_id,
            kind=DuetMessageKind.OVERRIDE,
            expected_unit_index=sequence,
            code="human_guidance",
            guidance_artifact_ids=(guidance.guidance_id,),
        )
        self.service.submit_duet_decision(decision.message_id)
        return decision.message_id

    def decide_creator(self, kind: DuetMessageKind) -> OpaqueId:
        if kind not in {DuetMessageKind.PAUSE, DuetMessageKind.CANCEL, DuetMessageKind.RETRY}:
            raise ValueError("unsupported Creator boundary decision")
        creator_id, sequence = self._current_creator_boundary()
        decision = self.service.record_human_decision(
            self.identity,
            creator_episode_id=creator_id,
            kind=kind,
            expected_unit_index=sequence,
            code=f"human_{kind.value}",
        )
        self.service.submit_duet_decision(decision.message_id)
        return decision.message_id

    def status(self) -> dict[str, Any]:
        status = self.service.duet_status(self.identity.duet_id)
        creator_id = status.get("creator_episode_id")
        if creator_id:
            with self._lock:
                thread = self._creator_threads.get(creator_id)
                status["creator_thread_alive"] = bool(thread and thread.is_alive())
                status["creator_error_code"] = self._execution_errors.get(creator_id)
        else:
            status["creator_thread_alive"] = False
            status["creator_error_code"] = None
        launch = status.get("launch") or {}
        launch_id = launch.get("launch_id")
        if launch_id:
            with self._lock:
                final = self._final_threads.get(launch_id)
                if final is not None and final.is_alive():
                    final_state = "running"
                elif launch_id in self._final_errors:
                    final_state = "failed"
                elif launch_id in self._final_completed:
                    final_state = "completed"
                else:
                    final_state = "persisted_launch"
                status["final_run_state"] = final_state
                status["final_error_code"] = self._final_errors.get(launch_id)
        else:
            status["final_run_state"] = "idle"
            status["final_error_code"] = None
        return status

    def has_active_work(self) -> bool:
        """Return whether a Creator experiment or approved workflow is running."""

        with self._lock:
            return any(thread.is_alive() for thread in self._creator_threads.values()) or any(
                thread.is_alive() for thread in self._final_threads.values()
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
