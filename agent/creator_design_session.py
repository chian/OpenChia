"""Model conversation adapter for one task-specific Creator Episode.

The method loop asks this adapter for one frozen workflow candidate at a time.
The conversational model may inspect logs from earlier Run Episodes and submit
several invalid proposals, but exactly one host-admitted design can close a
design cycle.  Approval and final workflow launch remain Duet operations.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from agent.creator_episode import (
    CandidateDesigner,
    RunEpisodeResult,
    WorkflowCandidateDesign,
)
from agent.duet_contracts import DuetDecision, canonical_json
from agent.duet_service import DuetService
from agent.episode_contracts import OpaqueId
from method_loop import EpisodeView


class CreatorDesignCycleError(RuntimeError):
    """A Creator conversation ended without one admitted workflow design."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "candidate_not_admitted",
        details: Optional[Mapping[str, Any]] = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})
        self.retryable = retryable


class CreatorDesignSession(CandidateDesigner):
    """Bridge a restricted Creator AIAgent into the generic Episode source."""

    def __init__(
        self,
        *,
        service: DuetService,
        creator_episode_id: OpaqueId,
        agent: Any,
        activity_publisher: Optional[
            Callable[[str, str, Mapping[str, Any]], None]
        ] = None,
    ) -> None:
        if not isinstance(service, DuetService):
            raise TypeError("CreatorDesignSession requires a DuetService")
        if not isinstance(creator_episode_id, OpaqueId):
            raise TypeError("creator_episode_id must be an OpaqueId")
        if not callable(getattr(agent, "chat", None)):
            raise TypeError("CreatorDesignSession requires an agent with chat()")
        self.service = service
        self.creator_episode_id = creator_episode_id
        self.agent = agent
        self.activity_publisher = activity_publisher
        self.frozen_contract = service.creator_contract(creator_episode_id)
        self._pending: Optional[WorkflowCandidateDesign] = None

    def _activity(
        self,
        stage: str,
        activity_code: str,
        details: Mapping[str, Any],
    ) -> None:
        if self.activity_publisher is not None:
            self.activity_publisher(stage, activity_code, details)

    def _submit(self, workflow_blueprint: Mapping[str, Any]) -> WorkflowCandidateDesign:
        if self._pending is not None:
            raise CreatorDesignCycleError(
                "this design cycle already has a frozen workflow candidate"
            )
        creator_contract = self.frozen_contract.contract.creator_contract
        if creator_contract is None:
            raise CreatorDesignCycleError(
                "Creator Episode lacks its structured Creator contract"
            )
        design = self.service.freeze_workflow_design(
            creator_episode_id=self.creator_episode_id,
            workflow_blueprint=workflow_blueprint,
            consumed_context_artifact_ids=tuple(
                sorted(getattr(self.agent, "_creator_context_read_ids", set()))
            ),
        )
        candidate = WorkflowCandidateDesign(
            revision=design.revision,
            artifact_id=design.artifact_id,
            workflow=design.workflow,
        )
        self._pending = candidate
        return candidate

    @staticmethod
    def _run_summary(result: RunEpisodeResult) -> dict[str, Any]:
        """Closed goal/log record visible to the next Creator design cycle."""

        return result.as_record()

    def next_candidate(
        self,
        view: EpisodeView,
        previous_runs: tuple[RunEpisodeResult, ...],
        boundary_messages: tuple[DuetDecision, ...],
    ) -> Optional[WorkflowCandidateDesign]:
        references = getattr(self.agent, "_creator_log_references", None)
        if not isinstance(references, dict):
            raise CreatorDesignCycleError("Creator agent has no scoped Run log store")
        for result in previous_runs:
            references[result.log.artifact_id.value] = result.log

        self._pending = None
        self.agent._creator_last_candidate_result = None
        self.agent._creator_workflow_submit = self._submit
        self._activity(
            "designing",
            "design_cycle_started",
            {
                "unit_index": view.units_consumed,
                "previous_run_count": len(previous_runs),
                "boundary_message_count": len(boundary_messages),
            },
        )
        request = {
            "operation": "design_next_workflow_candidate",
            "creator_episode_id": self.creator_episode_id.value,
            "creator_contract_artifact_id": self.frozen_contract.artifact_id.value,
            "creator_contract_hash": self.frozen_contract.content_hash.value,
            "creator_contract": self.frozen_contract.contract.as_record(),
            "creator_context": (
                None
                if self.frozen_contract.contract.creator_contract is None
                else self.frozen_contract.contract.creator_contract.design_context.as_record()
            ),
            "unit_index": view.units_consumed,
            "previous_run_results": [
                self._run_summary(item) for item in previous_runs
            ],
            "duet_boundary_messages": list(
                self.service.creator_boundary_records(boundary_messages)
            ),
            "review_policy": {
                "required_before_submission": False,
                "invocation": "human_slash_review_only",
                "authority": (
                    "This agent cannot invoke critics. Deterministic host validation "
                    "and measurements, not critic opinion, govern admission and credit."
                ),
            },
            "required_action": (
                "Read every required Creator context artifact exactly with "
                "creator_context_read, inspect any useful prior Run log with "
                "creator_log_read, then "
                "draft a complete workflow and submit exactly one complete blueprint "
                "with workflow_candidate. Do not invoke or simulate a semantic review; "
                "only the human-facing /review command may launch critics. "
                "A tool result with accepted=false is a structured repair request: read "
                "its reason, message, and deficits, correct only the candidate, and call "
                "the tool again. Do not end this conversation until workflow_candidate "
                "returns accepted=true unless the host interrupts the attempt."
            ),
        }
        try:
            self.agent.chat(canonical_json(request))
        finally:
            self.agent._creator_workflow_submit = None
        if self._pending is None:
            rejection = getattr(
                self.agent,
                "_creator_last_candidate_result",
                None,
            )
            if isinstance(rejection, Mapping):
                reason = str(rejection.get("reason") or "candidate_rejected")
                raise CreatorDesignCycleError(
                    "Creator submitted no admissible workflow candidate: "
                    f"{reason}",
                    code="candidate_rejected",
                    details={"candidate_submission": dict(rejection)},
                )
            raise CreatorDesignCycleError(
                "Creator conversation ended without submitting a workflow candidate",
                code="candidate_not_submitted",
            )
        return self._pending


__all__ = ["CreatorDesignCycleError", "CreatorDesignSession"]
