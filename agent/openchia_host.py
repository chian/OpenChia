"""OpenChia host authority, workspace, build, and explicit Run boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Optional

from agent.duet_contracts import (
    ApprovalKind,
    DUET_PROTOCOL_TOOLS,
    DUET_SEARCH_TOOLS,
    OPENCHIA_CONTROL_PLANE_TOOLS,
    DuetDesignState,
    DuetIdentity,
    DuetPolicy,
    DuetProvenance,
    DuetProtocolError,
    canonical_json,
    content_id,
)
from agent.duet_service import DuetService
from agent.duet_store import DuetConflictError, DuetStore
from agent.episode_contracts import OpaqueId, Sha256Digest
from agent.openchia_agents import bind_duet_agent
from iterative_episode_refiner.workspace import RefinementWorkspace
from iterative_episode_refiner.contracts import (
    DuetWorkspaceNote,
    RefinementBaseline,
    RefinementCycleState,
    RefinementDecision,
    RefinementProposal,
)
from iterative_episode_refiner.service import (
    MATERIALIZED_SPECIFICATION_ARTIFACT_KIND,
    RUN_EVIDENCE_ARTIFACT_KIND,
)
from episode_builder import (
    ApprovedBuildRequest,
    BuildAttempt,
    BuildManifest,
    BuildReceipt,
    BuildStore,
    EpisodeBuilder,
    WorkflowMaterializationPlan,
)
from episode_runtime import (
    CredentialSpec,
    HttpxHostTransport,
    RunEvidence,
    RunRegistration,
    RunStore,
    RunStoreNotFound,
    RuntimePolicy,
    ScopedHttpBroker,
    ScopedModelBroker,
    RunExecutor,
    inspect_runtime_identity,
    load_egress_config,
)
from handoff_library import (
    DuetLaunchAddress,
    DuetLaunchRequest,
    HandoffPayloadContract,
    admit_duet_launch_request,
)
from llm_call_library import (
    CallOptions,
    ModelTier,
    ModelTransportRequest,
    ModelTransportResponse,
    call_model_transport,
    model_transport_scope,
)


logger = logging.getLogger(__name__)


def _operator_egress_ceiling() -> tuple[
    tuple[str, ...], Mapping[str, CredentialSpec]
]:
    """The operator's ``openchia.egress`` ceiling; closed when unreadable.

    Only credential names and file paths are loaded here; token files are
    read by the broker at request time and never at construction.
    """

    try:
        from openchia_cli.config import load_config_readonly

        return load_egress_config(load_config_readonly() or {})
    except Exception as exc:
        logger.warning(
            "ignoring openchia.egress config (%s: %s); no egress hosts or "
            "credentials are allowed",
            type(exc).__name__,
            exc,
        )
        return (), {}


_INITIAL_EDITABLE_STATES = frozenset(
    {
        DuetDesignState.DESIGNING.value,
        DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
    }
)


class OpenChiaHostError(RuntimeError):
    """The host cannot honor an exact Duet or Builder operation."""


@dataclass(frozen=True)
class HumanActionReceipt:
    kind: str
    artifact_id: OpaqueId
    approval_id: OpaqueId


class OpenChiaHost:
    """Persistent authority, materialization, and Run host for one Duet."""

    def __init__(
        self,
        *,
        home: str | Path,
        session_id: str,
        available_tool_names: Iterable[str],
        agent_kwargs_factory: Callable[[str, str], dict[str, Any]],
        run_executor_factory: Optional[
            Callable[[RunStore], RunExecutor]
        ] = None,
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("OpenChia requires a non-empty session_id")
        if not callable(agent_kwargs_factory):
            raise TypeError("agent_kwargs_factory must be callable")
        self.root = Path(home).expanduser().resolve() / "openchia"
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = DuetStore(self.root / "authority.sqlite3")
        self.build_store = BuildStore(self.root / "episode_builder")
        self.run_store = RunStore(self.root / "episode_runs")
        self.available_tool_names = frozenset(
            name
            for name in available_tool_names
            if isinstance(name, str)
            and name
            and name not in OPENCHIA_CONTROL_PLANE_TOOLS
        )
        self.agent_kwargs_factory = agent_kwargs_factory
        if run_executor_factory is not None and not callable(
            run_executor_factory
        ):
            raise TypeError("run_executor_factory must be callable or None")
        self._run_executor_factory = run_executor_factory
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
        self.egress_hosts, self.egress_credentials = _operator_egress_ceiling()
        self.service = DuetService(
            self.store,
            allowed_episode_capabilities=(),
            allowed_egress_hosts=self.egress_hosts,
            egress_credential_names=tuple(sorted(self.egress_credentials)),
        )
        self.refiner = self.service.refiner
        try:
            self.service.open_duet(self.identity, self.policy)
        except Exception:
            self.store.close()
            raise
        self._duet_agent: Any = None
        self.workspace = RefinementWorkspace(
            identity=self.identity,
            authority=self.service,
            refiner=self.refiner,
            store=self.store,
            build_store=self.build_store,
            run_store=self.run_store,
        )
        self._architecture_lock = threading.RLock()
        self._build_lock = threading.RLock()
        self._build_thread: Optional[threading.Thread] = None
        self._build_cancel_event: Optional[threading.Event] = None
        self._build_state = "not_started"
        self._build_progress = self._empty_progress("not_started")
        self._build_request: Optional[ApprovedBuildRequest] = None
        self._build_attempt_id: Optional[OpaqueId] = None
        self._build_receipt: Optional[BuildReceipt] = None
        self._build_baseline: Optional[RefinementBaseline] = None
        self._build_error: Optional[str] = None
        self._build_model_call_active = False
        self._build_model_call_task: Optional[str] = None
        self._build_model_call_token: Optional[object] = None
        self._build_model_call_started_at: Optional[float] = None
        self._build_last_model_response_at: Optional[float] = None
        self._run_lock = threading.RLock()
        self._run_thread: Optional[threading.Thread] = None
        self._run_loop: Optional[asyncio.AbstractEventLoop] = None
        self._run_task: Optional[asyncio.Task[RunEvidence]] = None
        self._run_cancel_requested = False
        self._run_state = "not_started"
        self._run_registration: Optional[RunRegistration] = None
        self._run_evidence: Optional[RunEvidence] = None
        self._run_baseline: Optional[RefinementBaseline] = None
        self._run_error: Optional[str] = None

    def close(self) -> None:
        self.cancel_run()
        self.cancel_build()
        with self._run_lock:
            run_worker = self._run_thread
        with self._build_lock:
            build_worker = self._build_thread
        for worker in (run_worker, build_worker):
            if worker is not None and worker is not threading.current_thread():
                worker.join()
        self.store.close()

    @staticmethod
    def _empty_progress(stage: str) -> dict[str, Any]:
        return {
            "stage": stage,
            "local_id": None,
            "build_attempt_id": None,
            "counts": {
                "episodes_total": 0,
                "episodes_planned": 0,
                "episodes_emitted": 0,
                "blocking_deficits": 0,
            },
        }

    def _role_agent_kwargs(self, role: str, identity: str) -> dict[str, Any]:
        kwargs = self.agent_kwargs_factory(role, identity)
        if not isinstance(kwargs, dict):
            raise TypeError("agent_kwargs_factory must return a dictionary")
        return kwargs

    def bind_duet(self, agent: Any) -> Any:
        bound = bind_duet_agent(
            agent,
            service=self.service,
            identity=self.identity,
            policy=self.policy,
        )
        bound._episode_architecture_submitter = self.submit_episode_architecture
        bound._episode_workspace_reader = self.read_episode_workspace
        bound._episode_refinement_requester = self.request_episode_refinement
        self._duet_agent = bound
        return bound

    def _run_is_active(self) -> bool:
        with self._run_lock:
            return bool(
                self._run_thread is not None
                and self._run_thread.is_alive()
            )

    def _require_no_active_run(self, operation: str) -> None:
        if self._run_is_active():
            raise DuetProtocolError(
                f"{operation} requires the current Episode Run to finish"
            )

    @staticmethod
    def _draft_receipt(artifact: Mapping[str, Any]) -> dict[str, Any]:
        record = artifact.get("record")
        if not isinstance(record, Mapping):
            raise OpenChiaHostError("stored Architecture draft is malformed")
        return {
            "accepted": True,
            "revision": int(artifact["revision"]),
            "artifact_id": artifact["artifact_id"],
            "content_hash": artifact["content_hash"],
            "workflow_hash": record.get("workflow_hash"),
            "ready": bool(record.get("ready")),
            "validation_deficits": list(
                record.get("validation_deficits") or ()
            ),
            "human_note_ids": list(record.get("human_note_ids") or ()),
        }

    def architecture_snapshot(self) -> dict[str, Any]:
        """Return the exact UI projection of the current Architecture."""

        return self.workspace.architecture_snapshot()

    def episode_workspace_snapshot(self) -> dict[str, Any]:
        """Return both workspace views over one captured authority head."""

        return self.workspace.snapshot()

    def read_episode_workspace(
        self,
        *,
        target_id: Optional[str] = None,
        note_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Resolve a current target or one exact historical human note."""

        return self.workspace.read(target_id=target_id, note_id=note_id)

    def record_workspace_note(
        self,
        target_record: Mapping[str, Any],
        body: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Persist exact human text against one exact workspace target."""

        with self._build_lock:
            if self._build_thread is not None and self._build_thread.is_alive():
                raise DuetProtocolError(
                    "workspace notes require a stable materialized baseline"
                )
            return self.workspace.record_note(
                target_record,
                body,
                idempotency_key,
            )

    def record_global_instruction(
        self,
        body: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], ...]:
        """Atomically anchor one prompt to both layers of a stable workspace."""

        with self._build_lock:
            if (
                self._build_thread is not None
                and self._build_thread.is_alive()
            ) or self._run_is_active():
                return ()
            return self.workspace.record_global_instruction(
                body,
                idempotency_key,
            )

    def _initial_note_ids(
        self,
        note_ids: tuple[str, ...],
        *,
        expected_artifact_id: Optional[str],
        expected_content_hash: Optional[str],
    ) -> tuple[OpaqueId, ...]:
        result = tuple(OpaqueId(value) for value in note_ids)
        if expected_artifact_id is None:
            if result:
                raise DuetProtocolError(
                    "the first Architecture cannot cite notes before a draft exists"
                )
            return result
        for note_id in result:
            artifact = self.refiner.read_artifact(
                self.identity.duet_id,
                note_id,
            )
            note = DuetWorkspaceNote.from_record(artifact["record"])
            if (
                note.baseline_id is not None
                or note.target.artifact_id.value != expected_artifact_id
                or note.target.artifact_hash.value != expected_content_hash
            ):
                raise DuetProtocolError(
                    "Architecture submission cites a note from another revision"
                )
        return result

    def _record_architecture(
        self,
        *,
        candidate_workflow_architecture: Mapping[str, Any],
        expected_artifact_id: Optional[str],
        expected_content_hash: Optional[str],
        expected_revision: Optional[int],
        human_note_ids: tuple[str, ...],
        source_stage: str,
    ) -> dict[str, Any]:
        cas_values = (
            expected_artifact_id,
            expected_content_hash,
            expected_revision,
        )
        if any(value is None for value in cas_values) and not all(
            value is None for value in cas_values
        ):
            raise ValueError(
                "Architecture CAS identity, hash, and revision move together"
            )
        status = self.service.duet_status(self.identity.duet_id)
        current = status.get("episode_workflow_draft")
        if expected_artifact_id is None:
            if current is not None:
                raise DuetConflictError(
                    "an Architecture draft already exists; submit its exact CAS"
                )
        else:
            snapshot = self.workspace.architecture_snapshot()
            if not snapshot["editable"]:
                raise DuetProtocolError(
                    "approved Architecture changes require a refinement request"
                )
            if (
                snapshot["source_artifact_id"] != expected_artifact_id
                or snapshot["content_hash"] != expected_content_hash
                or snapshot["revision"] != expected_revision
            ):
                raise DuetConflictError(
                    "Architecture changed or was superseded during editing"
                )
        note_ids = self._initial_note_ids(
            human_note_ids,
            expected_artifact_id=expected_artifact_id,
            expected_content_hash=expected_content_hash,
        )
        artifact = self.service.record_initial_workflow_draft(
            duet_id=self.identity.duet_id,
            workflow_blueprint=candidate_workflow_architecture,
            expected_draft_artifact_id=expected_artifact_id,
            expected_draft_hash=expected_content_hash,
            expected_draft_revision=expected_revision,
            source_stage=source_stage,
            human_note_ids=note_ids,
        )
        return self._draft_receipt(artifact)

    def submit_episode_architecture(
        self,
        *,
        candidate_workflow_architecture: Mapping[str, Any],
        expected_artifact_id: Optional[str],
        expected_content_hash: Optional[str],
        expected_revision: Optional[int],
        human_note_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        """Accept a complete initial Architecture candidate from the Duet LLM."""

        with self._architecture_lock:
            return self._record_architecture(
                candidate_workflow_architecture=(
                    candidate_workflow_architecture
                ),
                expected_artifact_id=expected_artifact_id,
                expected_content_hash=expected_content_hash,
                expected_revision=expected_revision,
                human_note_ids=human_note_ids,
                source_stage="duet",
            )

    def record_architecture_revision(
        self,
        *,
        candidate_workflow_architecture: Mapping[str, Any],
        expected_artifact_id: str,
        expected_content_hash: str,
        expected_revision: int,
        human_note_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Apply one direct human edit to the still-mutable Architecture."""

        with self._architecture_lock:
            return self._record_architecture(
                candidate_workflow_architecture=(
                    candidate_workflow_architecture
                ),
                expected_artifact_id=expected_artifact_id,
                expected_content_hash=expected_content_hash,
                expected_revision=expected_revision,
                human_note_ids=human_note_ids,
                source_stage="human_edit",
            )

    def request_episode_refinement(
        self,
        *,
        baseline_id: str,
        candidate_workflow_architecture: Mapping[str, Any],
        human_note_ids: tuple[str, ...],
        implementation_directives: tuple[Mapping[str, str], ...],
    ) -> dict[str, Any]:
        """Translate saved human notes into one host-classified successor."""

        with self._build_lock:
            self._require_no_active_run("refinement")
            if self._build_thread is not None and self._build_thread.is_alive():
                raise DuetProtocolError(
                    "refinement requires a stable completed build baseline"
                )
            return self.refiner.request(
                self.identity,
                baseline_id=baseline_id,
                candidate_workflow_architecture=(
                    candidate_workflow_architecture
                ),
                human_note_ids=human_note_ids,
                implementation_directives=implementation_directives,
            )

    def approve_current(self) -> HumanActionReceipt:
        """Approve the exact candidate named by the durable Duet lifecycle."""

        self._require_no_active_run("approval")
        status = self.service.duet_status(self.identity.duet_id)
        if status["state"] == DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value:
            draft = status.get("episode_workflow_draft")
            if not isinstance(draft, Mapping) or not draft.get("ready"):
                raise DuetProtocolError(
                    "current Architecture has blocking validation deficits"
                )
            authorization = self.service.approve_current_workflow(
                self.identity,
                source_draft_artifact_id=OpaqueId(draft["artifact_id"]),
                source_draft_hash=Sha256Digest(draft["content_hash"]),
            )
            approval = authorization.authority_approval
            return HumanActionReceipt(
                kind=ApprovalKind.WORKFLOW.value,
                artifact_id=authorization.frozen_workflow.artifact_id,
                approval_id=approval.approval_id,
            )
        if status["state"] == DuetDesignState.AWAITING_REFINEMENT_APPROVAL.value:
            active = status.get("active_refinement")
            decision_id = (
                None
                if not isinstance(active, Mapping)
                else active.get("decision_artifact_id")
            )
            if not isinstance(decision_id, str):
                raise DuetProtocolError(
                    "current refinement has no exact decision to approve"
                )
            approval = self.service.approve_current_implementation_refinement(
                self.identity,
                decision_id=OpaqueId(decision_id),
            )
            return HumanActionReceipt(
                kind=ApprovalKind.REFINEMENT.value,
                artifact_id=approval.artifact_id,
                approval_id=approval.approval_id,
            )
        raise DuetProtocolError("the Duet has no exact candidate awaiting approval")

    def decline_current_refinement(self) -> dict[str, Any]:
        """Reject the exact pending refinement and retain current authority."""

        self._require_no_active_run("refinement rejection")
        status = self.service.duet_status(self.identity.duet_id)
        active = status.get("active_refinement")
        if not isinstance(active, Mapping) or active.get("state") not in {
            RefinementCycleState.AWAITING_WORKFLOW_APPROVAL.value,
            RefinementCycleState.AWAITING_REFINEMENT_APPROVAL.value,
        }:
            raise DuetProtocolError(
                "the Duet has no exact refinement decision awaiting rejection"
            )
        refinement_id = active.get("refinement_id")
        decision_id = active.get("decision_artifact_id")
        if not isinstance(refinement_id, str) or not isinstance(
            decision_id,
            str,
        ):
            raise OpenChiaHostError(
                "pending refinement has no durable decision identity"
            )
        self.refiner.close(
            self.identity,
            refinement_id=OpaqueId(refinement_id),
            terminal_state=RefinementCycleState.REJECTED,
        )
        return {
            "refinement_id": refinement_id,
            "decision_id": decision_id,
            "state": RefinementCycleState.REJECTED.value,
        }

    def _load_refinement_chain(
        self,
        decision: RefinementDecision,
    ) -> tuple[
        RefinementBaseline,
        RefinementProposal,
        tuple[DuetWorkspaceNote, ...],
        BuildReceipt,
        Optional[BuildManifest],
    ]:
        baseline, proposal, notes = self.refiner.approved_chain(decision)
        _specification, receipt, manifest = self.workspace.materialized_context(
            baseline
        )
        return baseline, proposal, notes, receipt, manifest

    def _approved_build_request(self) -> ApprovedBuildRequest:
        authorization = self.service.resolve_current_build_authorization(
            self.identity.duet_id
        )
        decision = authorization.refinement_decision
        if decision is None:
            return ApprovedBuildRequest(
                authority_approval=authorization.authority_approval,
                workflow_approval=authorization.workflow_approval,
                frozen_workflow=authorization.frozen_workflow,
                admission_authority=authorization.admission_authority,
                request_nonce=secrets.token_hex(32),
            )
        baseline, proposal, notes, receipt, manifest = (
            self._load_refinement_chain(decision)
        )
        return ApprovedBuildRequest(
            authority_approval=authorization.authority_approval,
            workflow_approval=authorization.workflow_approval,
            frozen_workflow=authorization.frozen_workflow,
            admission_authority=authorization.admission_authority,
            request_nonce=secrets.token_hex(32),
            refinement_decision=decision,
            refinement_baseline=baseline,
            refinement_proposal=proposal,
            refinement_notes=notes,
            predecessor_receipt=receipt,
            predecessor_manifest=manifest,
        )

    def _builder_for(self, request: ApprovedBuildRequest) -> EpisodeBuilder:
        runtime = self._role_agent_kwargs(
            "episode_builder",
            request.build_request_id.value,
        )
        return EpisodeBuilder(
            store=self.build_store,
            call_options=CallOptions(
                tier=ModelTier.REASONING,
                main_runtime=runtime,
            ),
        )

    def _begin_build_model_call(self, task: str) -> object:
        now = time.monotonic()
        token = object()
        with self._build_lock:
            self._build_model_call_active = True
            self._build_model_call_task = task
            self._build_model_call_token = token
            self._build_model_call_started_at = now
        return token

    def _record_build_model_response(self, token: object) -> None:
        with self._build_lock:
            if (
                self._build_model_call_active
                and self._build_model_call_token is token
            ):
                self._build_last_model_response_at = time.monotonic()

    def _finish_build_model_call(self, token: object) -> None:
        with self._build_lock:
            if self._build_model_call_token is token:
                self._build_model_call_active = False
                self._build_model_call_token = None

    def _build_model_wait(self) -> Optional[dict[str, Any]]:
        started_at = self._build_model_call_started_at
        if started_at is None:
            return None
        last_response_at = self._build_last_model_response_at
        reference = (
            last_response_at
            if last_response_at is not None
            else started_at
        )
        return {
            "active": self._build_model_call_active,
            "task": self._build_model_call_task,
            "response_seen": last_response_at is not None,
            "elapsed_seconds": max(0, int(time.monotonic() - reference)),
        }

    async def _builder_model_transport(
        self,
        request: ModelTransportRequest,
        cancel_event: threading.Event,
    ) -> ModelTransportResponse:
        """Wait for a Builder model response until the human cancels the build."""

        from agent.auxiliary_client import (
            AuxiliaryExplicitCancellation,
            aux_interrupt_protection,
            aux_progress_hook,
            call_llm,
            extract_content_or_reasoning,
        )

        model_call_token = self._begin_build_model_call(request.task)
        route: dict[str, str] = {}

        def invoke() -> Any:
            with (
                aux_interrupt_protection(cancel_event=cancel_event),
                aux_progress_hook(
                    lambda: self._record_build_model_response(
                        model_call_token
                    )
                ),
            ):
                return call_llm(
                    task=request.task,
                    messages=[dict(item) for item in request.messages],
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    timeout=request.timeout,
                    main_runtime=(
                        None
                        if request.main_runtime is None
                        else dict(request.main_runtime)
                    ),
                    reasoning_config=(
                        None
                        if request.reasoning_config is None
                        else dict(request.reasoning_config)
                    ),
                    route_info=route,
                    wait_for_host_cancellation=True,
                )

        try:
            try:
                response = await asyncio.to_thread(invoke)
            except AuxiliaryExplicitCancellation:
                raise asyncio.CancelledError from None
            self._record_build_model_response(model_call_token)
            return ModelTransportResponse(
                text=extract_content_or_reasoning(response) or "",
                route=route,
            )
        finally:
            self._finish_build_model_call(model_call_token)

    @staticmethod
    def _validated_progress(
        progress: Mapping[str, object],
    ) -> dict[str, Any]:
        if not isinstance(progress, Mapping) or set(progress) != {
            "stage",
            "local_id",
            "build_attempt_id",
            "counts",
        }:
            raise OpenChiaHostError("Builder progress has an invalid shape")
        stage = progress["stage"]
        local_id = progress["local_id"]
        attempt_id = progress["build_attempt_id"]
        counts = progress["counts"]
        if not isinstance(stage, str) or not stage:
            raise OpenChiaHostError("Builder progress has no stage")
        if local_id is not None and (
            not isinstance(local_id, str) or not local_id
        ):
            raise OpenChiaHostError("Builder progress has an invalid Episode ID")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise OpenChiaHostError("Builder progress has no attempt identity")
        expected_counts = {
            "episodes_total",
            "episodes_planned",
            "episodes_emitted",
            "blocking_deficits",
        }
        if not isinstance(counts, Mapping) or set(counts) != expected_counts:
            raise OpenChiaHostError("Builder progress counts are malformed")
        normalized_counts: dict[str, int] = {}
        for name in sorted(expected_counts):
            value = counts[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise OpenChiaHostError(
                    f"Builder progress count {name!r} is invalid"
                )
            normalized_counts[name] = value
        return {
            "stage": stage,
            "local_id": local_id,
            "build_attempt_id": attempt_id,
            "counts": normalized_counts,
        }

    def _record_build_progress(
        self,
        request: ApprovedBuildRequest,
        progress: Mapping[str, object],
    ) -> None:
        record = self._validated_progress(progress)
        attempt_id = OpaqueId(record["build_attempt_id"])
        attempt = self.build_store.read_build_attempt(attempt_id)
        if attempt.build_request_id != request.build_request_id:
            raise OpenChiaHostError(
                "Builder progress attempt names another request"
            )
        with self._build_lock:
            if (
                self._build_request is None
                or self._build_request.build_request_id
                != request.build_request_id
            ):
                raise OpenChiaHostError(
                    "Builder progress belongs to a superseded request"
                )
            if self._build_attempt_id is not None and (
                self._build_attempt_id != attempt_id
            ):
                raise OpenChiaHostError(
                    "Builder progress changed attempt identity"
                )
            self._build_attempt_id = attempt_id
            self._build_progress = record
            if self._build_state != "cancel_requested":
                self._build_state = "building"
        self.store.append_event(
            duet_id=self.identity.duet_id.value,
            event_type="build_progress",
            provenance=DuetProvenance.HOST_VALIDATION.value,
            record={
                "build_request_id": request.build_request_id.value,
                **record,
            },
        )

    def _correlated_receipt(
        self,
        request: ApprovedBuildRequest,
        receipt: BuildReceipt,
    ) -> BuildReceipt:
        if receipt.build_request_id != request.build_request_id:
            raise OpenChiaHostError("build receipt names another request")
        inputs = self.build_store.inspection_inputs_for_receipt(
            receipt.receipt_id,
            verify_source_package=receipt.manifest_id is not None,
        )
        if inputs.build_request.as_record() != request.as_record():
            raise OpenChiaHostError(
                "stored build request differs from current approved request"
            )
        if inputs.receipt is None or inputs.receipt.as_record() != receipt.as_record():
            raise OpenChiaHostError("stored build receipt is stale")
        if inputs.build_attempt.build_attempt_id != receipt.build_attempt_id:
            raise OpenChiaHostError("build receipt attempt linkage is stale")
        if inputs.plan.plan_id != receipt.plan_id:
            raise OpenChiaHostError("build receipt plan linkage is stale")
        return inputs.receipt

    def _persist_materialized_specification(
        self,
        request: ApprovedBuildRequest,
        receipt: BuildReceipt,
    ) -> RefinementBaseline:
        specification = self.build_store.project_receipt(
            receipt.receipt_id,
            verify_source_package=receipt.manifest_id is not None,
        )
        if (
            specification.build_request_id != request.build_request_id
            or specification.build_attempt_id != receipt.build_attempt_id
            or specification.receipt_id != receipt.receipt_id
            or specification.workflow_hash
            != request.frozen_workflow.workflow_hash
        ):
            raise OpenChiaHostError(
                "Materialized Specification differs from its approved build"
            )
        self.store.put_artifact(
            artifact_id=specification.specification_id.value,
            duet_id=self.identity.duet_id.value,
            kind=MATERIALIZED_SPECIFICATION_ARTIFACT_KIND,
            revision=request.frozen_workflow.revision,
            content_hash=specification.content_hash.value,
            record=specification.as_record(),
        )
        manifest = (
            None
            if receipt.manifest_id is None
            else self.build_store.read_manifest(receipt.manifest_id)
        )
        baseline = RefinementBaseline(
            duet_id=self.identity.duet_id,
            authority_head_approval_id=(
                request.authority_approval.approval_id
            ),
            workflow_approval_id=request.workflow_approval.approval_id,
            frozen_workflow_artifact_id=request.frozen_workflow.artifact_id,
            workflow_hash=request.frozen_workflow.workflow_hash,
            build_request_id=request.build_request_id,
            build_attempt_id=receipt.build_attempt_id,
            build_receipt_id=receipt.receipt_id,
            build_receipt_hash=receipt.content_hash,
            materialized_specification_id=specification.specification_id,
            materialized_specification_hash=specification.content_hash,
            build_manifest_id=(
                None if manifest is None else manifest.manifest_id
            ),
            build_manifest_hash=(
                None
                if manifest is None
                else Sha256Digest.of_record(manifest.as_record())
            ),
        )
        return self.refiner.record_baseline(
            self.identity,
            baseline,
        )

    def start_build(self) -> dict[str, Any]:
        """Start one fresh, inert build attempt for current approved authority."""

        with self._build_lock:
            self._require_no_active_run("a new build")
            if self._build_thread is not None and self._build_thread.is_alive():
                raise OpenChiaHostError("an Episode build is already active")
            request = self._approved_build_request()
            builder = self._builder_for(request)
            cancel_event = threading.Event()
            self.build_store.put_build_request(request)
            self._build_request = request
            self._build_attempt_id = None
            self._build_receipt = None
            self._build_baseline = None
            self._build_error = None
            self._build_cancel_event = cancel_event
            self._build_state = "starting"
            self._build_model_call_active = False
            self._build_model_call_task = None
            self._build_model_call_token = None
            self._build_model_call_started_at = None
            self._build_last_model_response_at = None
            self._build_progress = self._empty_progress("starting")
            self._build_progress["counts"]["episodes_total"] = len(
                request.frozen_workflow.workflow.episodes
            )

            def build_worker() -> None:
                receipt: Optional[BuildReceipt] = None
                try:
                    async def build_transport(
                        model_request: ModelTransportRequest,
                    ) -> ModelTransportResponse:
                        return await self._builder_model_transport(
                            model_request,
                            cancel_event,
                        )

                    async def materialize() -> BuildReceipt:
                        with model_transport_scope(build_transport):
                            return await builder.build(
                                request,
                                progress_callback=lambda value: (
                                    self._record_build_progress(request, value)
                                ),
                                cancel_event=cancel_event,
                            )

                    result = asyncio.run(materialize())
                    receipt = self._correlated_receipt(request, result)
                    with self._build_lock:
                        self._build_receipt = receipt
                        self._build_attempt_id = receipt.build_attempt_id
                    baseline = self._persist_materialized_specification(
                        request,
                        receipt,
                    )
                    with self._build_lock:
                        self._build_baseline = baseline
                        self._build_state = receipt.status
                        self._build_progress = self._receipt_progress(
                            request,
                            receipt,
                        )
                    self.store.append_event(
                        duet_id=self.identity.duet_id.value,
                        event_type="build_finished",
                        provenance=DuetProvenance.HOST_VALIDATION.value,
                        record={
                            "build_request_id": request.build_request_id.value,
                            "build_attempt_id": receipt.build_attempt_id.value,
                            "build_receipt_id": receipt.receipt_id.value,
                            "status": receipt.status,
                            "materialized_specification_id": (
                                baseline.materialized_specification_id.value
                            ),
                            "refinement_baseline_id": baseline.baseline_id.value,
                        },
                    )
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    with self._build_lock:
                        self._build_state = "host_error"
                        self._build_error = error
                    self.store.append_event(
                        duet_id=self.identity.duet_id.value,
                        event_type="build_host_failure",
                        provenance=DuetProvenance.HOST_VALIDATION.value,
                        record={
                            "build_request_id": request.build_request_id.value,
                            "build_attempt_id": (
                                None
                                if self._build_attempt_id is None
                                else self._build_attempt_id.value
                            ),
                            "build_receipt_id": (
                                None if receipt is None else receipt.receipt_id.value
                            ),
                            "error": error,
                        },
                    )
                finally:
                    with self._build_lock:
                        self._build_model_call_active = False
                        self._build_model_call_token = None
                        self._build_thread = None
                        self._build_cancel_event = None

            worker = threading.Thread(
                target=build_worker,
                name=f"openchia-build-{request.build_request_id.value[-12:]}",
                daemon=False,
            )
            self._build_thread = worker
            self.store.append_event(
                duet_id=self.identity.duet_id.value,
                event_type="build_requested",
                provenance=DuetProvenance.HUMAN_INPUT.value,
                record={
                    "build_request_id": request.build_request_id.value,
                    "authority_head_approval_id": (
                        request.authority_approval.approval_id.value
                    ),
                    "workflow_approval_id": (
                        request.workflow_approval.approval_id.value
                    ),
                },
            )
            try:
                worker.start()
            except Exception:
                self._build_thread = None
                self._build_cancel_event = None
                self._build_state = "host_error"
                raise
        return self.build_status()

    def cancel_build(self) -> bool:
        """Signal cancellation to the active Builder and its model request."""

        with self._build_lock:
            worker = self._build_thread
            cancel_event = self._build_cancel_event
            if (
                worker is None
                or not worker.is_alive()
                or cancel_event is None
            ):
                return False
            if cancel_event.is_set():
                return True
            cancel_event.set()
            self._build_state = "cancel_requested"
            request_id = (
                None
                if self._build_request is None
                else self._build_request.build_request_id.value
            )
            attempt_id = (
                None
                if self._build_attempt_id is None
                else self._build_attempt_id.value
            )
        self.store.append_event(
            duet_id=self.identity.duet_id.value,
            event_type="build_cancel_requested",
            provenance=DuetProvenance.HUMAN_INPUT.value,
            record={
                "build_request_id": request_id,
                "build_attempt_id": attempt_id,
            },
        )
        return True

    def _receipt_progress(
        self,
        request: ApprovedBuildRequest,
        receipt: BuildReceipt,
    ) -> dict[str, Any]:
        plan = self.build_store.read_plan(receipt.plan_id)
        return {
            "stage": receipt.status,
            "local_id": None,
            "build_attempt_id": receipt.build_attempt_id.value,
            "counts": {
                "episodes_total": len(
                    request.frozen_workflow.workflow.episodes
                ),
                "episodes_planned": len(plan.nodes),
                "episodes_emitted": len(
                    receipt.emitted_module_ids_by_local_id
                ),
                "blocking_deficits": sum(
                    value.blocking for value in receipt.deficits
                ),
            },
        }

    def _current_in_memory_build(self) -> bool:
        duet = self.store.get_duet(self.identity.duet_id.value)
        if duet is None or self._build_request is None:
            return False
        return (
            duet["authority_head_approval_id"]
            == self._build_request.authority_approval.approval_id.value
        )

    def build_receipt(self) -> Optional[dict[str, Any]]:
        """Return the current authority head's latest exact build receipt."""

        with self._build_lock:
            if self._current_in_memory_build():
                return (
                    None
                    if self._build_receipt is None
                    else self._build_receipt.as_record()
                )
        baseline = self.workspace.current_baseline()
        if baseline is None:
            return None
        receipt = self.build_store.read_receipt(baseline.build_receipt_id)
        if receipt.content_hash != baseline.build_receipt_hash:
            raise OpenChiaHostError("current build receipt hash is stale")
        return receipt.as_record()

    def build_status(self) -> dict[str, Any]:
        """Return live or recovered build state for the current authority head."""

        with self._build_lock:
            if self._current_in_memory_build():
                request = self._build_request
                receipt = self._build_receipt
                baseline = self._build_baseline
                return {
                    "state": self._build_state,
                    "build_request_id": (
                        None
                        if request is None
                        else request.build_request_id.value
                    ),
                    "build_attempt_id": (
                        None
                        if self._build_attempt_id is None
                        else self._build_attempt_id.value
                    ),
                    "build_receipt_id": (
                        None if receipt is None else receipt.receipt_id.value
                    ),
                    "materialized_specification_id": (
                        None
                        if baseline is None
                        else baseline.materialized_specification_id.value
                    ),
                    "refinement_baseline_id": (
                        None if baseline is None else baseline.baseline_id.value
                    ),
                    "progress": json.loads(canonical_json(self._build_progress)),
                    "model_wait": self._build_model_wait(),
                    "error": self._build_error,
                }
        baseline = self.workspace.current_baseline()
        if baseline is None:
            return {
                "state": "not_started",
                "build_request_id": None,
                "build_attempt_id": None,
                "build_receipt_id": None,
                "materialized_specification_id": None,
                "refinement_baseline_id": None,
                "progress": self._empty_progress("not_started"),
                "model_wait": None,
                "error": None,
            }
        receipt = self.build_store.read_receipt(baseline.build_receipt_id)
        request = self.build_store.read_build_request(
            baseline.build_request_id
        )
        if (
            receipt.content_hash != baseline.build_receipt_hash
            or receipt.build_request_id != request.build_request_id
        ):
            raise OpenChiaHostError("recovered build chain is stale")
        return {
            "state": receipt.status,
            "build_request_id": request.build_request_id.value,
            "build_attempt_id": receipt.build_attempt_id.value,
            "build_receipt_id": receipt.receipt_id.value,
            "materialized_specification_id": (
                baseline.materialized_specification_id.value
            ),
            "refinement_baseline_id": baseline.baseline_id.value,
            "progress": self._receipt_progress(request, receipt),
            "model_wait": None,
            "error": None,
        }

    def _runnable_build_context(
        self,
    ) -> tuple[
        RefinementBaseline,
        ApprovedBuildRequest,
        BuildAttempt,
        BuildReceipt,
        BuildManifest,
        WorkflowMaterializationPlan,
        Path,
    ]:
        status = self.service.duet_status(self.identity.duet_id)
        if status["state"] != DuetDesignState.SEALED.value:
            raise DuetProtocolError(
                "an Episode Run requires sealed workflow authority"
            )
        baseline = self.workspace.current_baseline()
        if baseline is None:
            raise DuetProtocolError(
                "an Episode Run requires a completed materialized build"
            )
        _specification, receipt, manifest = self.workspace.materialized_context(
            baseline
        )
        if not receipt.materialized or manifest is None:
            raise DuetProtocolError(
                "the current build is not materialized and cannot run"
            )
        inputs = self.build_store.inspection_inputs_for_receipt(
            receipt.receipt_id,
            verify_source_package=True,
        )
        request = inputs.build_request
        attempt = inputs.build_attempt
        plan = inputs.plan
        if inputs.manifest is None or inputs.manifest != manifest:
            raise OpenChiaHostError(
                "the runnable build manifest differs from its admitted chain"
            )
        authorization = self.service.resolve_current_build_authorization(
            self.identity.duet_id
        )
        if (
            request.authority_approval
            != authorization.authority_approval
            or request.workflow_approval
            != authorization.workflow_approval
            or request.frozen_workflow
            != authorization.frozen_workflow
            or request.admission_authority
            != authorization.admission_authority
            or baseline.build_request_id != request.build_request_id
            or baseline.build_attempt_id != attempt.build_attempt_id
            or baseline.build_receipt_id != receipt.receipt_id
            or baseline.build_manifest_id != manifest.manifest_id
        ):
            raise OpenChiaHostError(
                "the runnable build differs from current workflow authority"
            )
        source_package = self.build_store.verify_source_package(manifest)
        return (
            baseline,
            request,
            attempt,
            receipt,
            manifest,
            plan,
            source_package,
        )

    @staticmethod
    def _root_launch_request(
        request: ApprovedBuildRequest,
        plan: WorkflowMaterializationPlan,
    ) -> DuetLaunchRequest:
        root_nodes = tuple(
            node
            for node in plan.nodes
            if node.local_id == plan.root_local_id
        )
        root_specs = tuple(
            episode
            for episode in request.frozen_workflow.workflow.episodes
            if episode.local_id == plan.root_local_id
            and episode.workflow_parent_local_id is None
        )
        if len(root_nodes) != 1 or len(root_specs) != 1:
            raise OpenChiaHostError(
                "the admitted build does not identify one exact root Episode"
            )
        root_node = root_nodes[0]
        root_spec = root_specs[0]
        if root_node.contract_hash != Sha256Digest.of_record(
            root_spec.contract.as_record()
        ):
            raise OpenChiaHostError(
                "the root materialization plan names another Episode contract"
            )
        goal_id = content_id(
            "goal",
            {"root_contract": root_spec.contract.as_record()},
        )
        address = DuetLaunchAddress(
            request_id=content_id(
                "launch_request",
                {"nonce": secrets.token_hex(32)},
            ).value,
            workflow_id=request.frozen_workflow.artifact_id.value,
            goal_id=goal_id.value,
        )
        payload_contract = HandoffPayloadContract.from_record(
            root_node.request_payload_contract
        )
        return admit_duet_launch_request(
            {
                "request_id": address.request_id,
                "workflow_id": address.workflow_id,
                "goal_id": address.goal_id,
                "artifact_ids_by_role": {},
                "measurements": {},
                "states": {},
                "flags": {},
            },
            address,
            payload_contract,
        )

    def _runtime_executor(self) -> RunExecutor:
        factory = self._run_executor_factory
        if factory is None:
            raise OpenChiaHostError(
                "Episode Run execution resources are not configured"
            )
        executor = factory(self.run_store)
        if not isinstance(executor, RunExecutor):
            raise TypeError(
                "run_executor_factory must return a RunExecutor "
                "(SystemdRunExecutor or ContainerRunExecutor)"
            )
        if executor.run_store is not self.run_store:
            raise OpenChiaHostError(
                "Run executor must use the host's exact append-only Run store"
            )
        repository_root = Path(__file__).resolve().parents[1]
        if executor.repository_root != repository_root:
            raise OpenChiaHostError(
                "Run executor must bind this exact OpenChia repository"
            )
        return executor

    def _persist_run_evidence(
        self,
        *,
        registration: RunRegistration,
        baseline: RefinementBaseline,
        evidence: RunEvidence,
    ) -> RefinementBaseline:
        validated = self.run_store.read_evidence(registration.run_id)
        if validated.as_record() != evidence.as_record():
            raise OpenChiaHostError(
                "executor evidence differs from the durable Run event chain"
            )
        if (
            registration.build_request_id != baseline.build_request_id
            or registration.build_attempt_id != baseline.build_attempt_id
            or registration.build_receipt_id != baseline.build_receipt_id
            or registration.manifest_id != baseline.build_manifest_id
            or evidence.registration_hash != registration.registration_hash
            or evidence.manifest_id != registration.manifest_id
        ):
            raise OpenChiaHostError(
                "Run evidence differs from its exact refinement baseline"
            )
        request = self.build_store.read_build_request(
            baseline.build_request_id
        )
        self.store.put_artifact(
            artifact_id=evidence.evidence_id.value,
            duet_id=self.identity.duet_id.value,
            kind=RUN_EVIDENCE_ARTIFACT_KIND,
            revision=request.frozen_workflow.revision,
            content_hash=evidence.content_hash.value,
            record=evidence.as_record(),
        )
        successor = RefinementBaseline(
            duet_id=baseline.duet_id,
            authority_head_approval_id=(
                baseline.authority_head_approval_id
            ),
            workflow_approval_id=baseline.workflow_approval_id,
            frozen_workflow_artifact_id=(
                baseline.frozen_workflow_artifact_id
            ),
            workflow_hash=baseline.workflow_hash,
            build_request_id=baseline.build_request_id,
            build_attempt_id=baseline.build_attempt_id,
            build_receipt_id=baseline.build_receipt_id,
            build_receipt_hash=baseline.build_receipt_hash,
            materialized_specification_id=(
                baseline.materialized_specification_id
            ),
            materialized_specification_hash=(
                baseline.materialized_specification_hash
            ),
            build_manifest_id=baseline.build_manifest_id,
            build_manifest_hash=baseline.build_manifest_hash,
            run_evidence_artifact_id=evidence.evidence_id,
            run_evidence_hash=evidence.content_hash,
        )
        return self.refiner.record_baseline(
            self.identity,
            successor,
        )

    def _read_terminal_evidence(
        self,
        registration: RunRegistration,
    ) -> Optional[RunEvidence]:
        try:
            return self.run_store.read_evidence(registration.run_id)
        except RunStoreNotFound:
            return None

    def start_run(self) -> dict[str, Any]:
        """Start one fresh, explicitly requested Run of the current build."""

        with self._build_lock:
            if self._build_thread is not None and self._build_thread.is_alive():
                raise OpenChiaHostError(
                    "an Episode build must finish before an Episode Run"
                )
            with self._run_lock:
                if (
                    self._run_thread is not None
                    and self._run_thread.is_alive()
                ):
                    raise OpenChiaHostError(
                        "an Episode Run is already active"
                    )
                (
                    baseline,
                    request,
                    attempt,
                    receipt,
                    manifest,
                    plan,
                    source_package,
                ) = self._runnable_build_context()
                launch_request = self._root_launch_request(request, plan)
                executor = self._runtime_executor()
                runtime_identity = executor.inspect_runtime_identity(
                    destination_root=self.run_store.runtime_sources_root,
                )
                registration = RunRegistration.from_admitted_build(
                    build_request=request,
                    build_attempt=attempt,
                    build_receipt=receipt,
                    build_manifest=manifest,
                    launch_request=launch_request,
                    runtime_identity=runtime_identity,
                    runtime_policy=RuntimePolicy(),
                )
                broker = ScopedModelBroker(call_model_transport)
                http_broker = ScopedHttpBroker(
                    policy=registration.egress_policy,
                    credentials=self.egress_credentials,
                    transport=HttpxHostTransport(),
                    max_frame_bytes=registration.runtime_policy.max_frame_bytes,
                )
                self._run_registration = registration
                self._run_evidence = None
                self._run_baseline = None
                self._run_error = None
                self._run_cancel_requested = False
                self._run_loop = None
                self._run_task = None
                self._run_state = "starting"

                def run_worker() -> None:
                    loop = asyncio.new_event_loop()
                    task = loop.create_task(
                        executor.execute(
                            registration=registration,
                            source_package_path=source_package,
                            model_broker=broker,
                            http_broker=http_broker,
                        )
                    )
                    with self._run_lock:
                        self._run_loop = loop
                        self._run_task = task
                        if self._run_cancel_requested:
                            task.cancel()
                        else:
                            self._run_state = "running"
                    evidence: Optional[RunEvidence] = None
                    error: Optional[str] = None
                    try:
                        evidence = loop.run_until_complete(task)
                    except asyncio.CancelledError:
                        try:
                            evidence = self._read_terminal_evidence(
                                registration
                            )
                        except Exception as exc:
                            error = f"{type(exc).__name__}: {exc}"
                    except BaseException as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        try:
                            evidence = self._read_terminal_evidence(
                                registration
                            )
                        except Exception as evidence_exc:
                            error = (
                                f"{error}; evidence: "
                                f"{type(evidence_exc).__name__}: {evidence_exc}"
                            )
                    try:
                        if evidence is not None:
                            durable_evidence = self.run_store.read_evidence(
                                registration.run_id
                            )
                            if (
                                durable_evidence.as_record()
                                != evidence.as_record()
                            ):
                                raise OpenChiaHostError(
                                    "executor result differs from durable Run evidence"
                                )
                            evidence = durable_evidence
                            with self._run_lock:
                                self._run_evidence = evidence
                            recorded_baseline = self._persist_run_evidence(
                                registration=registration,
                                baseline=baseline,
                                evidence=evidence,
                            )
                            with self._run_lock:
                                self._run_baseline = recorded_baseline
                                self._run_state = (
                                    evidence.terminal_status.value
                                )
                                self._run_error = error
                            self.store.append_event(
                                duet_id=self.identity.duet_id.value,
                                event_type="run_finished",
                                provenance=(
                                    DuetProvenance.HOST_VALIDATION.value
                                ),
                                record={
                                    "run_id": registration.run_id.value,
                                    "registration_hash": (
                                        registration.registration_hash.value
                                    ),
                                    "evidence_id": evidence.evidence_id.value,
                                    "evidence_hash": evidence.content_hash.value,
                                    "audit_log_id": (
                                        evidence.audit_log_id.value
                                    ),
                                    "audit_log_hash": (
                                        evidence.audit_log_hash.value
                                    ),
                                    "terminal_status": (
                                        evidence.terminal_status.value
                                    ),
                                    "refinement_baseline_id": (
                                        recorded_baseline.baseline_id.value
                                    ),
                                },
                            )
                        else:
                            with self._run_lock:
                                cancelled = self._run_cancel_requested
                                self._run_state = (
                                    "cancelled_before_claim"
                                    if cancelled
                                    else "host_error"
                                )
                                self._run_error = error
                            self.store.append_event(
                                duet_id=self.identity.duet_id.value,
                                event_type=(
                                    "run_cancelled_before_claim"
                                    if cancelled
                                    else "run_host_failure"
                                ),
                                provenance=(
                                    DuetProvenance.HOST_VALIDATION.value
                                ),
                                record={
                                    "run_id": registration.run_id.value,
                                    "registration_hash": (
                                        registration.registration_hash.value
                                    ),
                                    "error": error,
                                },
                            )
                    except Exception as exc:
                        with self._run_lock:
                            self._run_state = "host_error"
                            self._run_error = (
                                f"{type(exc).__name__}: {exc}"
                            )
                    finally:
                        if not task.done():
                            task.cancel()
                            try:
                                loop.run_until_complete(task)
                            except BaseException:
                                pass
                        loop.close()
                        with self._run_lock:
                            self._run_loop = None
                            self._run_task = None
                            self._run_thread = None

                worker = threading.Thread(
                    target=run_worker,
                    name=f"openchia-run-{registration.run_id.value[-12:]}",
                    daemon=False,
                )
                self._run_thread = worker
                self.store.append_event(
                    duet_id=self.identity.duet_id.value,
                    event_type="run_requested",
                    provenance=DuetProvenance.HUMAN_INPUT.value,
                    record={
                        "run_id": registration.run_id.value,
                        "registration_hash": (
                            registration.registration_hash.value
                        ),
                        "build_request_id": (
                            registration.build_request_id.value
                        ),
                        "build_attempt_id": (
                            registration.build_attempt_id.value
                        ),
                        "build_receipt_id": (
                            registration.build_receipt_id.value
                        ),
                        "manifest_id": registration.manifest_id.value,
                    },
                )
                try:
                    worker.start()
                except Exception:
                    self._run_thread = None
                    self._run_state = "host_error"
                    raise
        return self.run_status()

    def cancel_run(self) -> bool:
        """Cancel the one active executor task without resuming its Run."""

        with self._run_lock:
            worker = self._run_thread
            if worker is None or not worker.is_alive():
                return False
            if self._run_cancel_requested:
                return True
            self._run_cancel_requested = True
            self._run_state = "cancel_requested"
            loop = self._run_loop
            task = self._run_task
            registration = self._run_registration
            if loop is not None and task is not None and not task.done():
                loop.call_soon_threadsafe(task.cancel)
        self.store.append_event(
            duet_id=self.identity.duet_id.value,
            event_type="run_cancel_requested",
            provenance=DuetProvenance.HUMAN_INPUT.value,
            record={
                "run_id": (
                    None
                    if registration is None
                    else registration.run_id.value
                )
            },
        )
        return True

    def _current_in_memory_run(self) -> bool:
        registration = self._run_registration
        if registration is None:
            return False
        baseline = self.workspace.current_baseline()
        return bool(
            baseline is not None
            and baseline.build_request_id == registration.build_request_id
            and baseline.build_attempt_id == registration.build_attempt_id
            and baseline.build_receipt_id == registration.build_receipt_id
            and baseline.build_manifest_id == registration.manifest_id
        )

    @staticmethod
    def _run_status_record(
        *,
        state: str,
        registration: Optional[RunRegistration],
        evidence: Optional[RunEvidence],
        error: Optional[str],
    ) -> dict[str, Any]:
        return {
            "state": state,
            "run_id": (
                None if registration is None else registration.run_id.value
            ),
            "registration_hash": (
                None
                if registration is None
                else registration.registration_hash.value
            ),
            "build_request_id": (
                None
                if registration is None
                else registration.build_request_id.value
            ),
            "build_attempt_id": (
                None
                if registration is None
                else registration.build_attempt_id.value
            ),
            "build_receipt_id": (
                None
                if registration is None
                else registration.build_receipt_id.value
            ),
            "manifest_id": (
                None
                if registration is None
                else registration.manifest_id.value
            ),
            "evidence_id": (
                None if evidence is None else evidence.evidence_id.value
            ),
            "audit_log_id": (
                None if evidence is None else evidence.audit_log_id.value
            ),
            "terminal_status": (
                None
                if evidence is None
                else evidence.terminal_status.value
            ),
            "error": error,
        }

    def run_status(self) -> dict[str, Any]:
        """Return current-build Run identity and terminal state only."""

        with self._run_lock:
            if self._current_in_memory_run():
                return self._run_status_record(
                    state=self._run_state,
                    registration=self._run_registration,
                    evidence=self._run_evidence,
                    error=self._run_error,
                )
        baseline = self.workspace.current_baseline()
        if baseline is None:
            return self._run_status_record(
                state="not_started",
                registration=None,
                evidence=None,
                error=None,
            )
        evidence = self.workspace.evidence_from_baseline(baseline)
        if evidence is None:
            return self._run_status_record(
                state="not_started",
                registration=None,
                evidence=None,
                error=None,
            )
        registration = self.run_store.read_registration(evidence.run_id)
        return self._run_status_record(
            state=evidence.terminal_status.value,
            registration=registration,
            evidence=evidence,
            error=None,
        )

    def run_evidence(
        self,
        run_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Return exact validated terminal evidence, never an active prefix."""

        if run_id is not None:
            registration = self.run_store.read_registration(OpaqueId(run_id))
            if registration.duet_id != self.identity.duet_id:
                raise DuetProtocolError("Run belongs to another Duet")
            evidence = self._read_terminal_evidence(registration)
            return None if evidence is None else evidence.as_record()
        with self._run_lock:
            if self._current_in_memory_run():
                registration = self._run_registration
                if registration is None:
                    return None
                evidence = self._read_terminal_evidence(registration)
                return None if evidence is None else evidence.as_record()
        baseline = self.workspace.current_baseline()
        if baseline is None:
            return None
        evidence = self.workspace.evidence_from_baseline(baseline)
        return None if evidence is None else evidence.as_record()

    def run_audit_log(
        self,
        run_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Return the validated terminal audit log for one exact Run."""

        evidence_record = self.run_evidence(run_id)
        if evidence_record is None:
            return None
        evidence = RunEvidence.from_record(evidence_record)
        events = self.run_store.read_audit_log(evidence.run_id)
        return {
            "evidence_id": evidence.evidence_id.value,
            "evidence_hash": evidence.content_hash.value,
            "audit_log_id": evidence.audit_log_id.value,
            "audit_log_hash": evidence.audit_log_hash.value,
            "log_location": str(
                self.run_store.audit_log_location(evidence.run_id)
            ),
            "events": [event.as_record() for event in events],
        }

    def status(self) -> dict[str, Any]:
        """Return compact Duet, Architecture, build, and Run state."""

        status = self.service.duet_status(self.identity.duet_id)
        try:
            architecture = self.workspace.architecture_snapshot()
        except DuetProtocolError:
            architecture = None
        status["episode_architecture"] = architecture
        status["build"] = self.build_status()
        status["run"] = self.run_status()
        return status

    def has_active_work(self) -> bool:
        with self._build_lock, self._run_lock:
            build_active = bool(
                self._build_thread is not None
                and self._build_thread.is_alive()
            )
            run_active = bool(
                self._run_thread is not None
                and self._run_thread.is_alive()
            )
            return build_active or run_active


__all__ = [
    "HumanActionReceipt",
    "OpenChiaHost",
    "OpenChiaHostError",
]
