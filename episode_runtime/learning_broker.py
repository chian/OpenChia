"""Resolve learning authority from the admitted package, never worker arguments."""

from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact
from function_library.epistemic_schemas import canonical
from llm_call_library.calls import _parse_json

from .contracts import RunEventKind
from .learning import LearningLedger
from .linker import prepare_source_package


class LearningBroker:
    def __init__(self, store, registration, source_package):
        self.store, self.registration = store, registration
        prepared = prepare_source_package(registration, source_package)
        self.contracts = {
            node.grain_name: next(
                episode.contract
                for episode in prepared.build_request.frozen_workflow.workflow.episodes
                if episode.local_id == node.local_id
            )
            for node in prepared.plan.nodes
        }
        self.ledger = LearningLedger(store, registration.run_id)
        self.root_grain = next(
            node.grain_name
            for node in prepared.plan.nodes
            if node.parent_local_id is None
        )

    def _events(self):
        attestation = self.store.read_claim(self.registration.run_id)
        with self.store._claim_lock(self.registration.run_id):
            return self.store._load_event_chain_locked(self.registration, attestation)

    def _contract(self, episode_id):
        events = self._events()
        started = [
            event
            for event in events
            if event.kind is RunEventKind.EPISODE_STARTED
            and event.episode_id == episode_id
        ]
        if len(started) != 1:
            raise ValueError(
                "learning request needs exactly one started admitted Episode"
            )
        contract = self.contracts.get(started[0].payload["grain"])
        if contract is None or contract.epistemic is None:
            raise ValueError("Episode has no frozen learning authority")
        return contract

    async def __call__(self, episode_id, operation, payload):
        episode_id = OpaqueId(episode_id)
        contract = self._contract(episode_id)
        kwargs = {
            "episode_id": episode_id,
            "contract": contract.epistemic,
            "numerical_control": contract.numeric_control,
        }
        if operation == "retrieve":
            exact(payload, set(), "learning retrieval")
            return self.ledger.retrieve(**kwargs)
        if operation == "submit":
            exact(
                payload,
                {"ordinal", "result", "producer_call_id"},
                "learning submission",
            )
            from collections.abc import Mapping

            result = payload["result"]
            if isinstance(result, Mapping) and result.get("status") == "blocked":
                if any(
                    result.get(field)
                    for field in ("candidate_lessons", "entities", "revisions")
                ):
                    raise ValueError(
                        "an unauthenticated blocked outcome cannot propose state changes"
                    )
            else:
                producers = [
                    e
                    for e in self._events()
                    if e.kind is RunEventKind.MODEL_RESPONDED
                    and e.episode_id == episode_id
                    and e.payload.get("producer_call_id") == payload["producer_call_id"]
                ]
                if not producers or canonical(
                    _parse_json(producers[-1].payload["response_text"])
                ) != canonical(result):
                    raise ValueError(
                        "unit result is not the output of its committed producing call"
                    )
            return self.ledger.commit(**kwargs, **payload)
        if operation == "select":
            exact(
                payload,
                {"ordinal", "action_class", "action_inputs", "retry_reason"},
                "learning action selection",
            )
            return self.ledger.select(**kwargs, **payload)
        raise ValueError("unknown learning operation")

    def validate_completion(self, typed_status=None):
        """A worker cannot relabel an unfinished reasoning Episode as complete."""
        events = self._events()
        if any(contract.epistemic is not None for contract in self.contracts.values()):
            roots = [
                e
                for e in events
                if e.kind is RunEventKind.EPISODE_STARTED
                and e.payload["grain"] == self.root_grain
            ]
            if len(roots) != 1:
                raise ValueError(
                    "reasoning workflow must have exactly one started root"
                )
        for event in events:
            if event.kind is not RunEventKind.EPISODE_STARTED:
                continue
            contract = self.contracts.get(event.payload["grain"])
            if contract is None or contract.epistemic is None:
                continue
            history = self.ledger._history(events, event.episode_id)
            if (
                not history
                or history[-1].payload["receipt"]["terminal_state"] != "completed"
            ):
                raise ValueError(
                    "reasoning Episode has no committed yield-based completion"
                )
            if typed_status is not None and event.payload["grain"] == self.root_grain:
                if canonical(typed_status.get("workflow_result")) != canonical(
                    history[-1].payload["receipt"]
                ):
                    raise ValueError(
                        "worker result differs from the authoritative host projection"
                    )
