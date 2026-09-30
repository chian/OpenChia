"""Creator and Run Episode bindings for iterative workflow engineering.

A Creator Episode is a specialist design loop.  Each of its acquired units is
one child Run Episode for one frozen workflow candidate.  The Run Episode
executes the candidate's nested task Episodes, persists a complete host-owned
log, and returns the log location together with typed goal measurements.  The
next design cycle can inspect that log before proposing a revision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable, Optional, Protocol

from agent.duet_contracts import (
    CreatorProgressEnvelope,
    DuetDecision,
    DuetDesignState,
    DuetMessageKind,
    canonical_json,
)
from agent.episode_contracts import (
    ChildEpisodePhase,
    ChildEpisodeStopReason,
    ChildEpisodeUpdate,
    EpisodeCreationSpec,
    EpisodeWorkflowDesignProjection,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
)
from method_loop import (
    Context,
    Episode,
    EpisodeGoal,
    EpisodeRecord,
    EpisodeRef,
    EpisodeRequest,
    EpisodeTree,
    EpisodeUpdate,
    EpisodeView,
    Grain,
)


CREATOR_EPISODE_GRAIN = "creator_episode"
RUN_EPISODE_GRAIN = "run_episode"
TASK_EPISODE_GRAIN = "task_episode"
_VALIDATION_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


class RunEpisodeStopReason(str, Enum):
    TARGET_REACHED = "target_reached"
    NO_PROGRESS = "no_progress"
    BOUND_HIT = "bound_hit"
    SOURCE_EXHAUSTED = "source_exhausted"
    VALIDATION_FAILED = "validation_failed"
    ERROR = "error"
    CANCELLED = "cancelled"


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text without NUL bytes")
    return value


@dataclass(frozen=True)
class RunLogReference:
    """Host-minted location of the complete log for one candidate run."""

    artifact_id: OpaqueId
    digest: Sha256Digest
    location: str
    byte_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, OpaqueId):
            raise ValueError("artifact_id must be an OpaqueId")
        if not isinstance(self.digest, Sha256Digest):
            raise ValueError("digest must be a Sha256Digest")
        object.__setattr__(self, "location", _text(self.location, "location"))
        object.__setattr__(
            self, "byte_count", _non_negative_int(self.byte_count, "byte_count")
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id.value,
            "digest": self.digest.value,
            "location": self.location,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True)
class RunEpisodeResult:
    """Closed child-to-Creator result for one frozen workflow experiment."""

    candidate_revision: int
    candidate_artifact_id: OpaqueId
    workflow_hash: Sha256Digest
    run_episode_id: OpaqueId
    execution_run_id: OpaqueId
    goal_id: str
    goal_reached: bool
    stop_reason: RunEpisodeStopReason
    units_consumed: int
    goal_result_ids: tuple[OpaqueId, ...]
    accepted_evidence_ids: tuple[OpaqueId, ...]
    workflow_projection: EpisodeWorkflowDesignProjection
    log: RunLogReference
    validation_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_revision",
            _non_negative_int(self.candidate_revision, "candidate_revision"),
        )
        if not isinstance(self.candidate_artifact_id, OpaqueId):
            raise ValueError("candidate_artifact_id must be an OpaqueId")
        if not isinstance(self.workflow_hash, Sha256Digest):
            raise ValueError("workflow_hash must be a Sha256Digest")
        for name in ("run_episode_id", "execution_run_id"):
            if not isinstance(getattr(self, name), OpaqueId):
                raise ValueError(f"{name} must be an OpaqueId")
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        if not isinstance(self.goal_reached, bool):
            raise ValueError("goal_reached must be boolean")
        if not isinstance(self.stop_reason, RunEpisodeStopReason):
            raise ValueError("stop_reason must be a RunEpisodeStopReason")
        object.__setattr__(
            self, "units_consumed", _non_negative_int(self.units_consumed, "units_consumed")
        )
        for name in ("goal_result_ids", "accepted_evidence_ids"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, OpaqueId) for item in values
            ):
                raise ValueError(f"{name} must be a tuple of OpaqueIds")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be unique")
        if not isinstance(self.workflow_projection, EpisodeWorkflowDesignProjection):
            raise ValueError(
                "workflow_projection must be an EpisodeWorkflowDesignProjection"
            )
        if self.workflow_projection.workflow_hash != self.workflow_hash:
            raise ValueError("workflow projection and run result hashes differ")
        if not isinstance(self.log, RunLogReference):
            raise ValueError("every Run Episode result requires a RunLogReference")
        if not isinstance(self.validation_codes, tuple) or any(
            not isinstance(item, str) or _VALIDATION_CODE.fullmatch(item) is None
            for item in self.validation_codes
        ):
            raise ValueError("validation_codes must be closed identifier strings")
        if len(set(self.validation_codes)) != len(self.validation_codes):
            raise ValueError("validation_codes must be unique")

    @property
    def method_credit(self) -> float:
        return self.workflow_projection.method_credit

    def as_record(self) -> dict[str, Any]:
        return {
            "candidate_revision": self.candidate_revision,
            "candidate_artifact_id": self.candidate_artifact_id.value,
            "workflow_hash": self.workflow_hash.value,
            "run_episode_id": self.run_episode_id.value,
            "execution_run_id": self.execution_run_id.value,
            "goal_id": self.goal_id,
            "goal_reached": self.goal_reached,
            "stop_reason": self.stop_reason.value,
            "units_consumed": self.units_consumed,
            "goal_result_ids": [item.value for item in self.goal_result_ids],
            "accepted_evidence_ids": [
                item.value for item in self.accepted_evidence_ids
            ],
            "method_credit": self.method_credit,
            "workflow_projection": self.workflow_projection.as_record(),
            "log": self.log.as_record(),
            "validation_codes": list(self.validation_codes),
        }


class CreatorRunLogStore:
    """Write immutable Run Episode records beneath one explicit log root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def persist(self, record: EpisodeRecord) -> RunLogReference:
        if not isinstance(record, EpisodeRecord):
            raise TypeError("run log persistence requires an EpisodeRecord")
        payload = (canonical_json(record.as_record()) + "\n").encode("utf-8")
        digest = Sha256Digest.of_bytes(payload)
        artifact_id = OpaqueId.mint(
            "runlog", f"{record.episode_id}:{digest.value}"
        )
        target = self.root / f"{artifact_id.value}.json"
        if target.exists():
            if target.read_bytes() != payload:
                raise RuntimeError("run log artifact path contains different content")
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{artifact_id.value}.", suffix=".tmp", dir=self.root
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                Path(temporary_name).replace(target)
            finally:
                temporary = Path(temporary_name)
                if temporary.exists():
                    temporary.unlink()
        return RunLogReference(
            artifact_id=artifact_id,
            digest=digest,
            location=str(target),
            byte_count=len(payload),
        )

    def read(
        self,
        reference: RunLogReference,
        *,
        offset: int = 0,
        limit: int = 65_536,
    ) -> str:
        """Read a bounded slice after proving the reference belongs to this root."""

        if not isinstance(reference, RunLogReference):
            raise TypeError("log reads require a RunLogReference")
        offset = _non_negative_int(offset, "offset")
        limit = _non_negative_int(limit, "limit")
        if limit == 0 or limit > 1_048_576:
            raise ValueError("limit must lie in [1, 1048576]")
        path = Path(reference.location).expanduser().resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise PermissionError("run log is outside the Creator log root") from exc
        if path.name != f"{reference.artifact_id.value}.json":
            raise PermissionError("run log path does not match its artifact identity")
        payload = path.read_bytes()
        if len(payload) != reference.byte_count:
            raise RuntimeError("run log byte count no longer matches its reference")
        if Sha256Digest.of_bytes(payload) != reference.digest:
            raise RuntimeError("run log digest no longer matches its reference")
        return payload[offset : offset + limit].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class WorkflowCandidateDesign:
    """One frozen candidate proposed by the Creator's design source."""

    revision: int
    artifact_id: OpaqueId
    workflow: EpisodeWorkflowSpec

    def __post_init__(self) -> None:
        object.__setattr__(self, "revision", _non_negative_int(self.revision, "revision"))
        if self.revision == 0:
            raise ValueError("revision must be positive")
        if not isinstance(self.artifact_id, OpaqueId):
            raise ValueError("artifact_id must be an OpaqueId")
        if not isinstance(self.workflow, EpisodeWorkflowSpec):
            raise ValueError("workflow must be an EpisodeWorkflowSpec")


class CandidateDesigner(Protocol):
    """Propose the next candidate after optional inspection of prior run logs."""

    def next_candidate(
        self,
        view: EpisodeView,
        previous_runs: tuple[RunEpisodeResult, ...],
        boundary_messages: tuple[DuetDecision, ...],
    ) -> Optional[WorkflowCandidateDesign]: ...


class RunEpisodeBuilder(Protocol):
    def __call__(
        self,
        candidate: WorkflowCandidateDesign,
        creator_goal: EpisodeGoal,
    ) -> Episode: ...


@dataclass(frozen=True)
class CreatorControllerStep:
    stop: bool
    requests_transition: bool
    progress_value: float
    progress_delta: float
    successful_candidate: bool
    no_progress: bool


@dataclass(frozen=True)
class CreatorControllerState:
    observations: int
    progress_value: float
    best_credit: float
    stagnant_observations: int
    stagnation_anchor: float
    successful_candidate: bool
    no_progress: bool
    stop: bool


class CreatorDesignController:
    """Host-owned numerical controller for design--run--inspect cycles."""

    epoch = "creator_design_v1"

    def __init__(
        self,
        *,
        minimum_credit: float,
        minimum_delta: float,
        stagnation_observations: int,
    ) -> None:
        minimum_credit = _finite(minimum_credit, "minimum_credit")
        minimum_delta = _finite(minimum_delta, "minimum_delta")
        if not 0 <= minimum_credit <= 1:
            raise ValueError("minimum_credit must lie in [0, 1]")
        if minimum_delta <= 0:
            raise ValueError("minimum_delta must be positive")
        if stagnation_observations < 2:
            raise ValueError("stagnation_observations must be at least two")
        self.minimum_credit = minimum_credit
        self.minimum_delta = minimum_delta
        self.stagnation_observations = stagnation_observations
        self._credits: list[float] = []
        self._best_credit = 0.0
        self._stagnation_anchor = 0.0
        self._stagnant_observations = 0
        self._successful = False
        self._no_progress = False

    def observe(
        self, unit_label: str, value: object, *, is_root: bool
    ) -> CreatorControllerStep:
        if not isinstance(value, RunEpisodeResult):
            raise TypeError("Creator controller input must be a RunEpisodeResult")
        prior_best = self._best_credit
        current = value.method_credit if not value.validation_codes else 0.0
        self._credits.append(current)
        self._best_credit = max(self._best_credit, current)
        delta = self._best_credit - prior_best
        self._successful = (
            value.goal_reached
            and not value.validation_codes
            and current >= self.minimum_credit
        )
        if self._best_credit - self._stagnation_anchor >= self.minimum_delta:
            self._stagnation_anchor = self._best_credit
            self._stagnant_observations = 0
        else:
            self._stagnant_observations += 1
        self._no_progress = (
            self._stagnant_observations >= self.stagnation_observations
        )
        stop = self._successful or self._no_progress
        return CreatorControllerStep(
            stop=stop,
            requests_transition=False,
            progress_value=self._best_credit,
            progress_delta=delta,
            successful_candidate=self._successful,
            no_progress=self._no_progress,
        )

    def state(self) -> CreatorControllerState:
        return CreatorControllerState(
            observations=len(self._credits),
            progress_value=self._best_credit,
            best_credit=self._best_credit,
            stagnant_observations=self._stagnant_observations,
            stagnation_anchor=self._stagnation_anchor,
            successful_candidate=self._successful,
            no_progress=self._no_progress,
            stop=self._successful or self._no_progress,
        )

    def transitioned(self, epoch: str) -> "CreatorDesignController":
        raise ValueError("Creator design epochs change only through a new frozen contract")


class _CreatorCandidateSource:
    def __init__(
        self,
        *,
        designer: CandidateDesigner,
        run_builder: RunEpisodeBuilder,
        claim_boundary_messages: Callable[[int], tuple[DuetDecision, ...]],
    ) -> None:
        self.designer = designer
        self.run_builder = run_builder
        self.claim_boundary_messages = claim_boundary_messages
        self.terminal_boundary_kind: Optional[DuetMessageKind] = None

    @staticmethod
    def _prior_results(view: EpisodeView) -> tuple[RunEpisodeResult, ...]:
        results = tuple(update.controller_input for update in view.updates)
        if any(not isinstance(item, RunEpisodeResult) for item in results):
            raise TypeError("Creator history contains a non-RunEpisodeResult update")
        return results

    def next(self, view: EpisodeView) -> Optional[Episode]:
        messages = self.claim_boundary_messages(view.units_consumed)
        if any(message.kind is DuetMessageKind.CANCEL for message in messages):
            self.terminal_boundary_kind = DuetMessageKind.CANCEL
            return None
        if any(message.kind is DuetMessageKind.PAUSE for message in messages):
            self.terminal_boundary_kind = DuetMessageKind.PAUSE
            return None
        prior = self._prior_results(view)
        candidate = self.designer.next_candidate(view, prior, messages)
        if candidate is None:
            self.terminal_boundary_kind = None
            return None
        if prior and candidate.revision <= prior[-1].candidate_revision:
            raise ValueError("Creator candidate revisions must increase monotonically")
        run_episode = self.run_builder(candidate, view.goal)
        if not isinstance(run_episode, Episode):
            raise TypeError("RunEpisodeBuilder must return an Episode")
        if run_episode.grain.name != RUN_EPISODE_GRAIN:
            raise ValueError("Creator children must be Run Episodes")
        return run_episode


class RunResultProjector(Protocol):
    def __call__(
        self,
        candidate: WorkflowCandidateDesign,
        record: EpisodeRecord,
        log: RunLogReference,
    ) -> RunEpisodeResult: ...


def bind_run_episode(
    *,
    grain: Grain,
    candidate: WorkflowCandidateDesign,
    creator_goal: EpisodeGoal,
    source_factory: Callable[[EpisodeGoal], Any],
    log_store: CreatorRunLogStore,
    result_projector: RunResultProjector,
    bound: Optional[int] = None,
) -> Episode:
    """Bind one candidate execution to a mandatory log-and-goal projection."""

    if grain.name != RUN_EPISODE_GRAIN:
        raise ValueError("run Episode grain must use the run_episode name")
    run_goal = EpisodeGoal.child(
        creator_goal,
        objective={
            "kind": "evaluate_frozen_workflow_candidate",
            "candidate_revision": candidate.revision,
            "candidate_artifact_id": candidate.artifact_id.value,
            "workflow_hash": candidate.workflow.workflow_hash.value,
        },
        result_contract={
            "kind": "run_episode_result",
            "requires": ["run_log", "goal_information", "host_method_credit"],
        },
    )
    source = source_factory(run_goal)
    if not hasattr(source, "next"):
        raise TypeError("Run Episode source_factory must return a UnitSource")

    def to_parent(record: EpisodeRecord) -> EpisodeUpdate:
        log = log_store.persist(record)
        result = result_projector(candidate, record, log)
        if not isinstance(result, RunEpisodeResult):
            raise TypeError("RunResultProjector must return a RunEpisodeResult")
        if result.log != log:
            raise ValueError("Run Episode result must return its host-persisted log")
        if result.workflow_hash != candidate.workflow.workflow_hash:
            raise ValueError("Run Episode result must preserve the candidate hash")
        if result.candidate_artifact_id != candidate.artifact_id:
            raise ValueError("Run Episode result must preserve the candidate artifact")
        if result.run_episode_id.value != record.episode_id:
            raise ValueError("Run Episode result must preserve its Episode identity")
        if result.goal_id != record.goal.goal_id:
            raise ValueError("Run Episode result must preserve its Goal identity")
        if result.units_consumed != record.units_consumed:
            raise ValueError("Run Episode result must preserve its consumed-unit count")
        return EpisodeUpdate(
            record_id=record.episode_id,
            goal=record.goal,
            controller_input=result,
            prompt_context={
                "run_log_artifact_id": log.artifact_id.value,
                "run_log_location": log.location,
                "candidate_artifact_id": candidate.artifact_id.value,
                "workflow_hash": result.workflow_hash.value,
                "goal_reached": result.goal_reached,
                "method_credit": result.method_credit,
                "validation_codes": list(result.validation_codes),
            },
        )

    return Episode(
        grain=grain,
        key=f"candidate-{candidate.revision}-{candidate.workflow.workflow_hash.value[-12:]}",
        source=source,
        request=EpisodeRequest(goal=run_goal),
        to_parent=to_parent,
        bound=bound,
    )


def bind_creator_episode(
    *,
    key: str,
    goal: EpisodeGoal,
    grain: Grain,
    designer: CandidateDesigner,
    run_builder: RunEpisodeBuilder,
    claim_boundary_messages: Callable[[int], tuple[DuetDecision, ...]],
    proposal_bound: int,
    on_unit: Optional[Callable[[Any, Any, Any], Any]] = None,
    on_close: Optional[
        Callable[[EpisodeRecord, Optional[DuetMessageKind]], Any]
    ] = None,
    to_parent: Optional[Callable[[EpisodeRecord], EpisodeUpdate]] = None,
) -> Episode:
    """Compose the Creator loop; each unit is one complete candidate Run Episode."""

    if grain.name != CREATOR_EPISODE_GRAIN:
        raise ValueError("Creator Episode grain must use the creator_episode name")
    source = _CreatorCandidateSource(
        designer=designer,
        run_builder=run_builder,
        claim_boundary_messages=claim_boundary_messages,
    )
    return Episode(
        grain=grain,
        key=key,
        source=source,
        request=EpisodeRequest(goal=goal),
        on_unit=on_unit,
        on_close=(
            None
            if on_close is None
            else lambda record: on_close(record, source.terminal_boundary_kind)
        ),
        to_parent=to_parent,
        bound=proposal_bound,
    )


def creator_to_parent_update(
    record: EpisodeRecord,
    *,
    spec: EpisodeCreationSpec,
) -> EpisodeUpdate:
    """Project a nested Creator into the same closed update as any task child."""

    if not isinstance(spec, EpisodeCreationSpec):
        raise TypeError("spec must be an EpisodeCreationSpec")
    if record.scope_level != CREATOR_EPISODE_GRAIN:
        raise ValueError("nested Creator projection requires a Creator record")
    if not spec.can_create_episodes:
        raise ValueError("nested Creator projection requires a Creator contract")
    if len(record.path) < 2:
        raise ValueError("a root Creator has no containing Episode")
    state = record.controller_state
    if not isinstance(state, CreatorControllerState):
        raise TypeError("Creator controller returned an invalid state")
    latest = (
        None
        if not record.unit_records
        else record.unit_records[-1].controller_input
    )
    if latest is not None and not isinstance(latest, RunEpisodeResult):
        raise TypeError("Creator record contains an invalid Run result")
    if record.ended_by == "bound_hit":
        phase = ChildEpisodePhase.BOUND_HIT
        reason = ChildEpisodeStopReason.SAFETY_BOUND
    elif state.successful_candidate:
        phase = ChildEpisodePhase.SUCCEEDED
        reason = ChildEpisodeStopReason.TARGET_REACHED
    elif state.no_progress:
        phase = ChildEpisodePhase.STOPPED
        reason = ChildEpisodeStopReason.NO_PROGRESS
    else:
        phase = ChildEpisodePhase.STOPPED
        reason = ChildEpisodeStopReason.SOURCE_EXHAUSTED
    accepted_result_ids = (
        (latest.workflow_projection.artifact_id,)
        if phase is ChildEpisodePhase.SUCCEEDED and latest is not None
        else ()
    )
    delta = (
        0.0
        if not record.unit_records
        else float(
            getattr(record.unit_records[-1].controller_step, "progress_delta", 0.0)
        )
    )
    update = ChildEpisodeUpdate(
        child_episode_id=OpaqueId(record.episode_id),
        parent_episode_id=OpaqueId(
            EpisodeRef(run_id=record.run_id, path=record.path[:-1]).episode_id
        ),
        sequence=record.units_consumed,
        phase=phase,
        stop_reason=reason,
        progress_value=state.progress_value,
        progress_delta=delta,
        observations=state.observations,
        units_consumed=record.units_consumed,
        requests_transition=phase not in {
            ChildEpisodePhase.RUNNING,
            ChildEpisodePhase.SUCCEEDED,
        },
        spec_hash=spec.spec_hash,
        checkpoint_hash=Sha256Digest.of_record(record.as_record()),
        accepted_result_ids=accepted_result_ids,
    )
    return EpisodeUpdate(
        record_id=record.episode_id,
        goal=record.goal,
        controller_input=update,
        prompt_context={
            "child_update": update.as_record(),
            "workflow_design": (
                None
                if latest is None
                else latest.workflow_projection.as_record()
            ),
        },
    )


def creator_progress_envelope(
    record: EpisodeRecord,
    *,
    creator_episode_id: Optional[OpaqueId] = None,
    waiting_on_duet: bool = False,
    cancelled: bool = False,
) -> CreatorProgressEnvelope:
    """Project a Creator record into the closed Duet-facing status channel."""

    if record.scope_level != CREATOR_EPISODE_GRAIN:
        raise ValueError("progress projection requires a Creator Episode record")
    results = tuple(
        unit.episode_update.controller_input
        for unit in record.unit_records
        if unit.episode_update is not None
    )
    if any(not isinstance(item, RunEpisodeResult) for item in results):
        raise TypeError("Creator record contains an invalid Run Episode result")
    latest = results[-1] if results else None
    state = record.controller_state
    if cancelled:
        phase = DuetDesignState.CANCELLED
    elif waiting_on_duet:
        phase = DuetDesignState.WAITING_ON_DUET
    elif getattr(state, "successful_candidate", False):
        phase = DuetDesignState.SEALED
    elif record.ended_by == "bound_hit":
        phase = DuetDesignState.BOUND_HIT
    elif getattr(state, "no_progress", False):
        phase = DuetDesignState.NO_PROGRESS
    else:
        phase = DuetDesignState.DESIGNING
    validation_codes = () if latest is None else latest.validation_codes
    evidence_ids = () if latest is None else latest.accepted_evidence_ids
    authority_id = (
        OpaqueId(record.episode_id)
        if creator_episode_id is None
        else creator_episode_id
    )
    if not isinstance(authority_id, OpaqueId):
        raise TypeError("creator_episode_id must be an OpaqueId")
    return CreatorProgressEnvelope(
        creator_episode_id=authority_id,
        sequence=record.units_consumed,
        state=phase,
        candidate_revision=0 if latest is None else latest.candidate_revision,
        deficit_count=len(validation_codes),
        validation_codes=validation_codes,
        accepted_evidence_ids=evidence_ids,
        method_credit=None if latest is None else latest.method_credit,
    )


def creator_unit_progress_envelope(
    *,
    creator_episode_id: OpaqueId,
    sequence: int,
    result: RunEpisodeResult,
    step: CreatorControllerStep,
    proposal_bound: int,
) -> CreatorProgressEnvelope:
    """Project one completed experiment without exposing its log or prose."""

    if not isinstance(creator_episode_id, OpaqueId):
        raise TypeError("creator_episode_id must be an OpaqueId")
    sequence = _non_negative_int(sequence, "sequence")
    proposal_bound = _non_negative_int(proposal_bound, "proposal_bound")
    if sequence == 0:
        raise ValueError("a completed Creator unit must have a positive sequence")
    if not isinstance(result, RunEpisodeResult):
        raise TypeError("result must be a RunEpisodeResult")
    if not isinstance(step, CreatorControllerStep):
        raise TypeError("step must be a CreatorControllerStep")
    if step.successful_candidate:
        state = DuetDesignState.SEALED
    elif step.no_progress:
        state = DuetDesignState.NO_PROGRESS
    elif proposal_bound and sequence >= proposal_bound:
        state = DuetDesignState.BOUND_HIT
    else:
        state = DuetDesignState.REFINING
    return CreatorProgressEnvelope(
        creator_episode_id=creator_episode_id,
        sequence=sequence,
        state=state,
        candidate_revision=result.candidate_revision,
        deficit_count=len(result.validation_codes),
        validation_codes=result.validation_codes,
        accepted_evidence_ids=result.accepted_evidence_ids,
        method_credit=result.method_credit,
    )


def creator_episode_tree(
    *,
    creator_grain: Grain,
    run_grain: Grain,
    task_grain: Grain,
    max_depth: int,
    allow_recursive_creators: bool = False,
) -> EpisodeTree:
    """Declare bounded task nesting and, only when authorized, Creator cycles."""

    if (
        creator_grain.name != CREATOR_EPISODE_GRAIN
        or run_grain.name != RUN_EPISODE_GRAIN
        or task_grain.name != TASK_EPISODE_GRAIN
    ):
        raise ValueError("Creator Episode tree grains use fixed semantic names")
    if not isinstance(allow_recursive_creators, bool):
        raise TypeError("allow_recursive_creators must be boolean")
    children = {
        creator_grain: (run_grain,),
        run_grain: (
            (task_grain, creator_grain)
            if allow_recursive_creators
            else (task_grain,)
        ),
        task_grain: (
            (task_grain, creator_grain)
            if allow_recursive_creators
            else (task_grain,)
        ),
    }
    recursive_edges = (
        (
            (creator_grain.name, run_grain.name),
            (run_grain.name, task_grain.name),
            (run_grain.name, creator_grain.name),
            (task_grain.name, creator_grain.name),
        )
        if allow_recursive_creators
        else ()
    )
    return EpisodeTree(
        root=creator_grain,
        children=children,
        self_nesting=(task_grain.name,),
        recursive_edges=recursive_edges,
        max_depth=max_depth,
    )


__all__ = [
    "CREATOR_EPISODE_GRAIN",
    "RUN_EPISODE_GRAIN",
    "TASK_EPISODE_GRAIN",
    "CandidateDesigner",
    "CreatorControllerState",
    "CreatorControllerStep",
    "CreatorDesignController",
    "CreatorRunLogStore",
    "RunEpisodeBuilder",
    "RunEpisodeResult",
    "RunEpisodeStopReason",
    "RunLogReference",
    "RunResultProjector",
    "WorkflowCandidateDesign",
    "bind_creator_episode",
    "bind_run_episode",
    "creator_episode_tree",
    "creator_progress_envelope",
    "creator_unit_progress_envelope",
    "creator_to_parent_update",
]
