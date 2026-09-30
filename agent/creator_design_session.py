"""Model conversation adapter for one task-specific Creator Episode.

The method loop asks this adapter for one frozen workflow candidate at a time.
The conversational model may inspect logs from earlier Run Episodes and submit
several invalid proposals, but exactly one host-admitted design can close a
design cycle.  Approval and final workflow launch remain Duet operations.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

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


class CreatorDesignSession(CandidateDesigner):
    """Bridge a restricted Creator AIAgent into the generic Episode source."""

    def __init__(
        self,
        *,
        service: DuetService,
        creator_episode_id: OpaqueId,
        agent: Any,
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
        self.frozen_contract = service.creator_contract(creator_episode_id)
        self._pending: Optional[WorkflowCandidateDesign] = None

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
        self.agent._creator_workflow_submit = self._submit
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
                "required_before_submission": True,
                "core_lenses": [
                    "contract_alignment",
                    "measurement_evidence",
                    "capability_safety",
                ],
                "optional_lenses": [
                    "iteration_recovery",
                    "task_specific_skeptic",
                ],
                "authority": (
                    "Reviews are advisory diagnostics. Host measurements, not critic "
                    "opinion, determine method credit."
                ),
            },
            "required_action": (
                "Read every required Creator context artifact exactly with "
                "creator_context_read, inspect any useful prior Run log with "
                "creator_log_read, then "
                "draft a complete workflow, call workflow_review with the three core "
                "lenses and any relevant optional lenses, revise when findings are "
                "sound, then submit exactly one complete blueprint with workflow_candidate."
            ),
        }
        try:
            self.agent.chat(canonical_json(request))
        finally:
            self.agent._creator_workflow_submit = None
        if self._pending is None:
            raise CreatorDesignCycleError(
                "Creator conversation ended without an admitted workflow candidate"
            )
        return self._pending


__all__ = ["CreatorDesignCycleError", "CreatorDesignSession"]
