"""Host-owned learning transactions in the existing locked Run event journal.

The last learning event is a durable checkpoint, not an instruction stream.
No worker receives this store or a path into it.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Mapping

from agent.episode_contracts import OpaqueId
from function_library.epistemic import resolve_component
from function_library.epistemic_admission import applicable, scope_record
from function_library.epistemic_schemas import ArtifactEnvelope, canonical, identity
from function_library.models import _thaw_json
from numeric_control_library import MARGINAL_DOMINATED_HYPERVOLUME, compose_controller
from numeric_control_library.continuation import continuation_function_library
from numeric_control_library.credit_assignment import (
    CreditObservation,
    ResultColumnSchema,
)
from numeric_control_library.rarefaction import rarefaction_function_library

from .contracts import RunEventKind, RunEventOrigin
from .store import RunStore, RunStoreConflict
from .learning_repair import audit_submission, pending_submission, replay_repair


CREDIT_CHANNEL = identity("channel", {"schema": "epistemic-state-v1"})


class LearningLedger:
    def __init__(self, store: RunStore, run_id: OpaqueId) -> None:
        self.store, self.run_id = store, run_id

    @contextmanager
    def _transaction(self):
        registration = self.store.read_registration(self.run_id)
        attestation = self.store.read_claim(self.run_id)
        with self.store._claim_lock(self.run_id):
            events = list(
                self.store._load_event_chain_locked(registration, attestation)
            )
            if events and events[-1].terminal:
                raise RunStoreConflict("learning cannot mutate a terminal Run")

            def publish(kind, episode_id, payload):
                sequence = 1 + max(
                    (
                        e.sender_sequence
                        for e in events
                        if e.origin is RunEventOrigin.HOST_LEARNING
                    ),
                    default=-1,
                )
                event = self.store._new_event(
                    registration=registration,
                    attestation=attestation,
                    events=tuple(events),
                    origin=RunEventOrigin.HOST_LEARNING,
                    sender_sequence=sequence,
                    kind=kind,
                    episode_id=episode_id,
                    payload=payload,
                )
                self.store._publish_event(event)
                events.append(event)
                return event

            yield registration, events, publish

    @staticmethod
    def _state(events):
        return next(
            (
                _thaw_json(e.payload["state"])
                for e in reversed(events)
                if e.kind is RunEventKind.LEARNING_COMMITTED
            ),
            {"records": []},
        )

    @staticmethod
    def _history(events, episode_id):
        return [
            e
            for e in events
            if e.kind is RunEventKind.LEARNING_COMMITTED and e.episode_id == episode_id
        ]

    def _sources(self, contract, scope, episode_id, events, publish):
        existing = {
            e.payload["artifact"]["artifact_id"]: e.payload["artifact"]
            for e in events
            if e.kind is RunEventKind.LEARNING_EVIDENCE
        }
        admitted = {}
        for source in contract.evidence:
            artifact = ArtifactEnvelope(
                schema_id="openchia.approved-evidence",
                schema_version=1,
                run_id=self.run_id.value,
                episode_id=scope["key"],
                unit_id="approved-input",
                producer_call_id="exact-human-approved-contract",
                evidence_refs=(),
                body=source,
            ).as_record()
            ref = artifact["artifact_id"]
            if ref not in existing:
                publish(
                    RunEventKind.LEARNING_EVIDENCE,
                    episode_id,
                    {"artifact": artifact, "scope": scope},
                )
            admitted[ref] = artifact
        return admitted

    @staticmethod
    def _pin_policy(contract, numerical_control, episode_id, events, publish):
        policy = {
            "contract": contract.as_record(),
            "numerical_control": numerical_control.as_record(),
        }
        opened = next(
            (
                e
                for e in events
                if e.kind is RunEventKind.LEARNING_OPENED and e.episode_id == episode_id
            ),
            None,
        )
        if opened is None:
            publish(RunEventKind.LEARNING_OPENED, episode_id, policy)
        elif canonical(opened.payload) != canonical(policy):
            raise RunStoreConflict("the active reasoning contract is immutable")

    def retrieve(self, *, episode_id, contract, numerical_control, environment=None):
        contract.validate_components()
        with self._transaction() as (registration, events, publish):
            self._pin_policy(contract, numerical_control, episode_id, events, publish)
            scope = scope_record(
                contract,
                episode_id=episode_id.value,
                workflow_id=registration.launch_request.workflow_id,
            )
            evidence = self._sources(contract, scope, episode_id, events, publish)
            if environment is not None:
                scope["environment"] = _thaw_json(environment)
            state = self._state(events)
            records = [r for r in state["records"] if applicable(r, scope)]
            history = self._history(events, episode_id)
            unit_id = identity(
                "unit", {"episode_id": episode_id.value, "ordinal": len(history)}
            )
            avoided = {
                r["body"]["action_class"]
                for r in records
                if r["kind"] == "lesson" and not r["body"]["action_inputs"]
            }
            excluded = {
                r["body"]["action_class"]
                for r in records
                if r["kind"] == "lesson"
                and not r["body"]["action_inputs"]
                and r["body"]["policy_effect"]["strength"] == "enforceable"
            }
            return {
                "contract": contract.as_record(),
                "result_shape": _thaw_json(
                    resolve_component(
                        "result_schema", contract.components["result_schema"]
                    ).provenance["result_shape"]
                ),
                "next_ordinal": len(history),
                "pending_submission": pending_submission(
                    events, episode_id, unit_id, len(history)
                ),
                "selected_action": next(
                    (
                        _thaw_json(e.payload)
                        for e in events
                        if e.kind is RunEventKind.LEARNING_SELECTED
                        and e.episode_id == episode_id
                        and e.payload["ordinal"] == len(history)
                    ),
                    None,
                ),
                "applicable_lessons": [r for r in records if r["kind"] == "lesson"][
                    :128
                ],
                "possible_conflicts": [
                    r
                    for r in state["records"]
                    if r["scope"] == scope
                    and r["status"] == "contradicted_pending_resolution"
                ][:128],
                "reopened_routes": [
                    r
                    for r in state["records"]
                    if r["scope"]["key"] == scope["key"]
                    and (
                        r["status"] == "reopened"
                        or r["scope"]["environment"] != scope["environment"]
                    )
                ][:128],
                "entities": [r for r in records if r["kind"] == "entity"][:128],
                "evidence": list(evidence.values()),
                "allowed_actions": [
                    a for a in contract.allowed_actions if a not in excluded
                ],
                "recommended_actions": [
                    a for a in contract.allowed_actions if a not in avoided
                ],
                "retrieval_provenance": {
                    "scope": scope,
                    "head_event_id": events[-1].event_id.value if events else None,
                    "matching_records": len(records),
                    "bounded_to": 128,
                },
                "last_receipt": _thaw_json(history[-1].payload["receipt"])
                if history
                else None,
            }

    def select(
        self,
        *,
        episode_id,
        contract,
        numerical_control,
        ordinal,
        action_class,
        action_inputs,
        retry_reason,
    ):
        if (
            type(ordinal) is not int
            or ordinal < 0
            or not isinstance(retry_reason, str)
            or not isinstance(action_inputs, Mapping)
        ):
            raise ValueError("invalid reasoning action selection")
        with self._transaction() as (registration, events, publish):
            self._pin_policy(contract, numerical_control, episode_id, events, publish)
            history = self._history(events, episode_id)
            if ordinal != len(history) or (
                history
                and history[-1].payload["receipt"]["terminal_state"] != "continuing"
            ):
                raise RunStoreConflict("action selection is outside the active unit")
            scope = scope_record(
                contract,
                episode_id=episode_id.value,
                workflow_id=registration.launch_request.workflow_id,
            )
            lessons = [
                r
                for r in self._state(events)["records"]
                if applicable(r, scope)
                and r["kind"] == "lesson"
                and r["body"]["action_class"] == action_class
                and canonical(r["body"]["action_inputs"]) == canonical(action_inputs)
            ]
            reason = "allowed"
            if action_class not in contract.allowed_actions:
                reason = "undeclared_action"
            elif any(
                r["body"]["policy_effect"]["strength"] == "enforceable" for r in lessons
            ):
                reason = "enforceable_exclusion"
            elif lessons and not retry_reason.strip():
                reason = "advisory_retry_requires_explanation"
            selection = {
                "ordinal": ordinal,
                "action_class": action_class,
                "retry_reason": retry_reason,
                "action_inputs": action_inputs,
                "permitted": reason == "allowed",
                "reason": reason,
            }
            prior = next(
                (
                    e
                    for e in events
                    if e.kind is RunEventKind.LEARNING_SELECTED
                    and e.episode_id == episode_id
                    and e.payload["ordinal"] == ordinal
                ),
                None,
            )
            if prior is not None:
                if canonical(prior.payload) != canonical(selection):
                    raise RunStoreConflict("a unit's action selection is immutable")
            else:
                publish(RunEventKind.LEARNING_SELECTED, episode_id, selection)
            return selection

    @staticmethod
    def _controller(numerical_control):
        def resolve(library, selection):
            function = library.resolve(f"{selection.library}.{selection.function_id}")
            if (
                function.definition_id != selection.definition_id
                or function.interface != selection.interface
            ):
                raise ValueError("numerical selection drift")
            function.admit_arguments(selection.arguments)
            return function

        rarefaction = resolve(
            rarefaction_function_library, numerical_control.rarefaction
        )
        continuation = resolve(
            continuation_function_library, numerical_control.continuation
        )
        return compose_controller(
            schema=ResultColumnSchema((CREDIT_CHANNEL,), (0.0,)),
            epoch="epistemic-v1",
            credit_function=MARGINAL_DOMINATED_HYPERVOLUME,
            rarefaction_function=rarefaction,
            continuation_function=continuation,
            credit_parameters={},
            rarefaction_parameters=numerical_control.rarefaction.arguments,
            continuation_parameters=numerical_control.continuation.arguments,
        )((("reasoning", "host"),))

    def commit(
        self,
        *,
        episode_id,
        contract,
        numerical_control,
        ordinal,
        result,
        producer_call_id,
        repair_of=None,
    ):
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError("unit ordinal must be a nonnegative integer")
        contract.validate_components()
        request_hash = identity(
            "request",
            {
                "ordinal": ordinal,
                "result": result,
                "producer_call_id": producer_call_id,
                "contract": contract.as_record(),
                "numeric_control": numerical_control.as_record(),
                **({"repair_of": repair_of} if repair_of is not None else {}),
            },
        )
        with self._transaction() as (registration, events, publish):
            self._pin_policy(contract, numerical_control, episode_id, events, publish)
            history = self._history(events, episode_id)
            repair = replay_repair(events, episode_id, request_hash)
            if repair is not None:
                return repair
            if ordinal < len(history):
                old = history[ordinal].payload
                if old["request_hash"] != request_hash:
                    raise RunStoreConflict("a committed unit cannot change on retry")
                return _thaw_json(old["receipt"])
            if ordinal != len(history):
                raise RunStoreConflict("learning unit sequence must be contiguous")
            if (
                history
                and history[-1].payload["receipt"]["terminal_state"] != "continuing"
            ):
                raise RunStoreConflict("Episode already resolved continuation")
            scope = scope_record(
                contract,
                episode_id=episode_id.value,
                workflow_id=registration.launch_request.workflow_id,
            )
            evidence = self._sources(contract, scope, episode_id, events, publish)
            unit_id = identity(
                "unit", {"episode_id": episode_id.value, "ordinal": ordinal}
            )
            audit = audit_submission(
                events=events,
                publish=publish,
                episode_id=episode_id,
                unit_id=unit_id,
                request_hash=request_hash,
                producer_call_id=producer_call_id,
                result=result,
                repair_of=repair_of,
            )
            prior = self._state(events)
            functions = {
                role: resolve_component(role, ref).load()
                for role, ref in contract.components.items()
            }
            try:
                validated = functions["result_schema"](result)
            except (ValueError, TypeError, KeyError) as exc:
                # Representation repair is not a semantic observation. Do not
                # invoke admission, yield, rarefaction or continuation yet.
                repair = {
                    "repair_required": True,
                    "unit_id": unit_id,
                    "ordinal": ordinal,
                    "request_hash": request_hash,
                    "audit_ref": audit.event_id.value,
                    "result_schema": _thaw_json(contract.components["result_schema"]),
                    "validation_error": str(exc),
                    "rejected_result": _thaw_json(result),
                }
                repair["repair_id"] = identity("repair", repair)
                publish(RunEventKind.LEARNING_REPAIR_REQUESTED, episode_id, repair)
                return repair
            terminal = "blocked" if validated["status"] == "blocked" else "continuing"
            result_artifact = None
            try:
                result_artifact = ArtifactEnvelope(
                    schema_id=contract.components["result_schema"]["function_id"],
                    schema_version=1,
                    episode_id=episode_id.value,
                    run_id=self.run_id.value,
                    unit_id=unit_id,
                    producer_call_id=producer_call_id,
                    evidence_refs=(audit.event_id.value,),
                    body=validated,
                ).as_record()
                if validated["action_class"] not in contract.allowed_actions:
                    raise ValueError("undeclared reasoning action")
                selected = next(
                    (
                        e
                        for e in events
                        if e.kind is RunEventKind.LEARNING_SELECTED
                        and e.episode_id == episode_id
                        and e.payload["ordinal"] == ordinal
                    ),
                    None,
                )
                if (
                    selected is None
                    or not selected.payload["permitted"]
                    or selected.payload["action_class"] != validated["action_class"]
                    or canonical(selected.payload["action_inputs"])
                    != canonical(validated["action_inputs"])
                ):
                    terminal = "blocked"
                    raise ValueError(
                        "result does not follow a permitted action selection"
                    )
                exclusions = [
                    r
                    for r in prior["records"]
                    if applicable(r, scope)
                    and r["kind"] == "lesson"
                    and r["body"]["action_class"] == validated["action_class"]
                    and canonical(r["body"]["action_inputs"])
                    == canonical(validated["action_inputs"])
                    and r["body"]["policy_effect"]["strength"] == "enforceable"
                ]
                if exclusions:
                    raise ValueError(
                        "action is excluded under the current approved conditions"
                    )
                delta = functions["admission"](
                    contract=contract,
                    result=validated,
                    candidates=functions["state_projector"](validated),
                    prior_state=prior,
                    evidence=evidence,
                    scope=scope,
                    audit_ref=audit.event_id.value,
                )
            except (ValueError, TypeError, KeyError) as exc:
                delta = {
                    "state": prior,
                    "transitions": [],
                    "rejections": [{"reason": str(exc)}],
                }
            measurement = functions["yield_function"](
                prior_state=prior, next_state=delta["state"], admitted_delta=delta
            )
            if measurement["realized_yield"] > 0 and not delta["transitions"]:
                raise ValueError("positive yield without admitted state is prohibited")
            measurement["function"] = _thaw_json(contract.components["yield_function"])
            controller = self._controller(numerical_control)
            baseline_ids = (
                list(history[0].payload["baseline_ids"])
                if history
                else sorted(
                    r.get("equivalence_key", r["record_id"])
                    for r in prior["records"]
                    if applicable(r, scope)
                )
            )
            if baseline_ids:
                controller.observe(
                    "existing-knowledge",
                    CreditObservation.excluded(
                        {CREDIT_CHANNEL: baseline_ids}, code="baseline"
                    ),
                    is_root=True,
                )
            for old in history:
                controller.observe(
                    "recovered",
                    CreditObservation.observed({
                        CREDIT_CHANNEL: old.payload["observation_ids"]
                    }),
                    is_root=True,
                )
            # Historical credit remains monotonic, while only operative records
            # participate in the next incidence observation.
            observation_ids = sorted({
                r.get("equivalence_key", r["record_id"])
                for r in delta["state"]["records"]
                if applicable(r, scope)
            })
            step = controller.observe(
                unit_id,
                CreditObservation.observed({CREDIT_CHANNEL: observation_ids}),
                is_root=True,
            )
            if terminal == "continuing" and step.stop:
                terminal = "completed"
            before = sum(
                e.payload["receipt"]["measurement"]["realized_yield"] for e in history
            )
            measurement.update(
                credit_before=before,
                credit_after=before + measurement["realized_yield"],
            )
            projection = functions["result_projection"]({
                "records": [r for r in delta["state"]["records"] if r["scope"] == scope]
            })
            receipt = {
                "unit_id": unit_id,
                "ordinal": ordinal,
                "audit_ref": audit.event_id.value,
                "components": _thaw_json(contract.components),
                "result_artifact": result_artifact,
                "measurement": measurement,
                "admission": {k: delta[k] for k in ("transitions", "rejections")},
                "numeric_step": step.as_record(),
                "terminal_state": terminal,
                "stop": terminal == "completed",
                "result": projection,
            }
            receipt["receipt_id"] = identity("receipt", receipt)
            publish(
                RunEventKind.LEARNING_COMMITTED,
                episode_id,
                {
                    "request_hash": request_hash,
                    "unit_id": unit_id,
                    "state": delta["state"],
                    "baseline_ids": baseline_ids,
                    "observation_ids": observation_ids,
                    "receipt": receipt,
                },
            )
            return receipt
