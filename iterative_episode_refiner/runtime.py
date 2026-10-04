"""One host session for the nested refiner; no separate worker or replay runner.

The existing executor carries requests here. All roles use the same campaign
store and evaluation entry point. A session is bound to an exact approved refiner
Run, not inferred from a worker-supplied campaign ID.
"""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass

from agent.duet_contracts import content_id
from agent.duet_store import DuetNotFoundError
from agent.episode_contracts import OpaqueId
from episode_library.refinement import (
    LAUNCH_DESIGN,
    ROLE_DESIGNS,
    materialization_bindings,
)
from episode_runtime.contracts import RunEventKind, RunEventOrigin
from episode_runtime.linker import prepare_source_package
from episode_runtime.protocol import episode_id_for_path
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json
from function_library.refinement_contract import REQUEST_PAYLOAD, RESULT_PAYLOAD, ROLES
from handoff_library import (
    ParentRequestAddress,
    admit_child_result,
    admit_parent_request,
)
from llm_call_library.calls import _parse_json
from method_loop import EpisodeGoal
from method_loop.identities import EpisodeRef

from .campaign_store import CampaignView
from .readiness import root_readiness
from .records import Ref, RefinementRecord
from .reports import decision_context, report_overview
from .measure_controls import control_context
from .grounding import grounding_context
from .measure_needs import assigned_context, catalog as measure_needs
from .measure_design import context as measure_design_context
from .instrument_builds import add_context as instrument_context, relevant_sources


@dataclass
class Invocation:
    invocation_id: OpaqueId
    assignment: RefinementRecord
    path: tuple
    goal: EpisodeGoal
    request: object = None
    unit_id: OpaqueId | None = None
    candidate_before: Ref | None = None
    feedback_ref: Ref | None = None


class RefinementSession:
    def __init__(
        self, *, store, campaign_id, registration, source_package_path, evaluations,
        terminal_recovery=False,
    ):
        self.store = store
        self.campaign_id = campaign_id
        self.registration = registration
        self.evaluations = evaluations
        self._operation_ordinal = 0
        self.calls = {}
        self.pending = {}
        self.initial_state_recorded = False
        prepared = prepare_source_package(registration, source_package_path)
        self.plan = prepared.plan
        self.nodes = {
            node.interface.removeprefix("refinement."): node for node in self.plan.nodes
        }
        designs = {
            item.binding.interface.removeprefix("refinement."): item
            for item in (LAUNCH_DESIGN, *ROLE_DESIGNS)
        }
        frozen_nodes = {
            node.local_id: node
            for node in prepared.build_request.frozen_workflow.workflow.episodes
        }
        if (
            len(self.plan.nodes) != len(designs)
            or set(self.nodes) != set(designs)
            or any(
                node.interface != design.binding.interface
                or set(node.child_slot_names)
                != {slot.name for slot in design.binding.child_slots}
                or frozen_nodes[node.local_id].episode_reference is None
                or frozen_nodes[node.local_id].episode_reference.episode_id
                != design.episode_id
                or node.result_channel_names != ("report",)
                or any(
                    required not in node.as_record()["selected_function_bindings"]
                    for required in materialization_bindings(
                        frozen_nodes[node.local_id].episode_reference
                    )
                )
                for entry, node in self.nodes.items()
                for design in (designs[entry],)
            )
        ):
            raise ValueError("refiner Run must declare the fixed refinement role graph")
        self.nodes_by_grain = {node.grain_name: node for node in self.plan.nodes}
        root = self.nodes["launch"]
        if root.local_id != self.plan.root_local_id:
            raise ValueError("the refiner's root must be Parts")
        self.edges = {
            (edge.parent_local_id, edge.slot_name): edge for edge in self.plan.all_edges
        }
        with self.view() as view:
            self.contract = view.contract
            self.duet_id = view.head["duet_id"]
            self.policy = self.store.evidence.reference(
                Ref.from_record(self.contract.body["policy_bundle_ref"]),
                self.duet_id,
            )
            catalog = self.store.evidence.reference(
                Ref.from_record(self.contract.body["requirement_catalog_ref"]),
                self.duet_id,
            )
            self.requirements = catalog["requirements"]
            self.materialization_handoff = self.store.evidence.reference(
                Ref.from_record(catalog["materialization_handoff_ref"]), self.duet_id
            )
            self.materialization = self.store.evidence.reference(
                Ref.from_record(self.contract.body["initial_materialization_ref"]),
                self.duet_id,
            )
            if any(
                node.contract.numeric_control.as_record()
                != self.policy["numeric_control"]
                for node in prepared.build_request.frozen_workflow.workflow.episodes
            ):
                raise ValueError(
                    "campaign numerical control differs from the approved refiner"
                )
            roots = [
                row
                for row in view.entries("invocation")
                if row.record.body["parent_assignment_ref"] is None
            ]
            if len(roots) != 1 or (
                registration.resume_from is None and not terminal_recovery and roots[0].status != "active"
            ):
                raise ValueError(
                    "explicit refiner launch requires one active root assignment"
                )
            assignment = roots[0].record
            path = ((root.grain_name, registration.logical_run_id.value),)
            # This is the same root goal construction used by the existing linker.
            goal = EpisodeGoal.root(
                objective=next(
                    node.contract.goal
                    for node in prepared.build_request.frozen_workflow.workflow.episodes
                    if node.local_id == root.local_id
                ),
                result_contract=root.result_payload_contract,
                task_context={
                    "duet_launch_request": registration.launch_request.as_record()
                },
            )
            self.root_id = EpisodeRef(
                run_id=registration.logical_run_id.value, path=path
            ).episode_id
            self.calls[self.root_id] = Invocation(
                OpaqueId(roots[0].key), assignment, path, goal
            )
        self.validate_registration(registration)
        if terminal_recovery:
            from .runtime_state import restore_terminal_session

            restore_terminal_session(self)
        elif registration.resume_from is not None:
            from .runtime_state import restore_session

            restore_session(self)

    @contextmanager
    def view(self):
        with self.store.duet_store.transaction() as connection:
            yield CampaignView(connection, self.campaign_id)

    def continuation_state(self):
        from .runtime_state import continuation_state

        return continuation_state(self)

    def validate_registration(self, registration):
        if registration.registration_hash != self.registration.registration_hash:
            raise ValueError("refinement session belongs to another Run")
        self.store.evidence.validate_contract(self.contract)
        approval = Ref.from_record(self.contract.body["refiner_workflow_approval_ref"])
        manifest = Ref.from_record(self.contract.body["refiner_manifest_ref"])
        if (
            approval.artifact_id != registration.workflow_approval_id
            or approval.content_hash != registration.workflow_approval_hash
            or manifest.artifact_id != registration.manifest_id
            or manifest.content_hash != registration.manifest_hash
        ):
            raise ValueError("Run differs from the campaign's exact approved refiner")

    def _caller(self, episode_id, episode_path):
        if episode_id_for_path(self.registration.logical_run_id, episode_path) != episode_id:
            raise ValueError("refinement caller has the wrong runtime path")
        call = self.calls.get(episode_id.value)
        path = tuple((part["grain"], part["key"]) for part in episode_path)
        if call is None or call.path != path:
            raise ValueError("no host-admitted assignment for this runtime invocation")
        return call

    async def exchange(self, *, episode_id, episode_path, operation, payload, request_event=None):
        call = self._caller(episode_id, episode_path)
        if operation == "evaluate":
            self._require_unit(call, payload)
            if "experiment_proposal_ref" in payload:
                from .evaluation_experiments import execute_experiment

                return await execute_experiment(
                    self.evaluations, self, call, payload, request_event=request_event
                )
        task = asyncio.create_task(asyncio.to_thread(
            self._dispatch_committed, call, episode_id, operation, payload, request_event
        ))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancelling an await cannot stop a Python thread. Let the local
            # transaction and its reply finish before the executor finalizes.
            return await task

    def _dispatch_committed(self, call, episode_id, operation, payload, request_event):
        return self.commit_response(
            request_event, self._dispatch, call, episode_id, operation, payload
        )

    def commit_response(self, request_event, operation, *args):
        from episode_runtime.records.host_operations import commit_receipt

        # All campaign writes made by a synchronous operation, its in-memory
        # call projection, and its response have one crash boundary.
        with self.store.duet_store.transaction():
            response = operation(*args)
            if request_event is not None:
                commit_receipt(
                    self.store.duet_store, self.registration, request_event,
                    response, self.continuation_state(),
                )
            return response

    def _dispatch(self, call, episode_id, operation, payload):
        payload = _thaw_json(payload)
        handlers = {
            "context": self._context,
            "begin_unit": self._begin_unit,
            "propose": self._propose,
            "prepare_child": self._prepare_child,
            "enter_child": self._enter_child,
            "receive_child": self._receive_child,
            "close_unit": self._close_unit,
            "report": self._report,
            "evaluate": lambda call, _episode_id, payload: self.evaluations.evaluate_local(self, call, payload),
        }
        handler = handlers.get(operation)
        if handler is None:
            raise ValueError("unregistered refinement host operation")
        return handler(call, episode_id, payload)

    def record(self, call, kind, body, *, producer=None, evidence=()):
        return RefinementRecord(
            kind,
            self.campaign_id,
            body,
            producer or self.contract.producer_ref,
            evidence_refs=tuple(evidence),
            invocation_id=call.invocation_id,
            logical_unit_id=call.unit_id,
        )

    def commit(self, call, action, payload, *, producer=None, evidence=()):
        if call.unit_id is None:
            raise ValueError("campaign operation has no open semantic unit")
        operation_id = content_id(
            "refinement_operation",
            {
                "run_id": self.registration.logical_run_id.value,
                "invocation_id": call.invocation_id.value,
                "ordinal": self._operation_ordinal,
            },
        )
        self._operation_ordinal += 1
        attempt = self.record(
            call,
            "attempt",
            {
                "operation_id": operation_id.value,
                "invocation_id": call.invocation_id.value,
                "logical_unit_id": call.unit_id.value,
                "action": action,
                "payload": payload,
            },
            producer=producer,
            evidence=evidence,
        )
        return self.store.commit_attempt(attempt)

    def snapshot(self, call, *, history_query=None):
        from episode_runtime.records.refinement import assigned_history
        from .evaluation_experiments import feedback
        from .runtime_proposals import proposal_schemas
        from .measures import admitted_measures, authorized_check_refs
        from .judgment import assessment_status, current_check_states, judgment_purpose
        from .investigation import catalog, reference_data, visible_findings
        from .materialization_edits import edit_context
        from .candidate_source import source_kind
        from .prerequisites import prerequisite_status
        from .evaluation_plan import evaluation_availability, resolve_evaluations
        from .succession import context_bundle
        from .measure_groups import declarations, group_definition

        local = self.store.context(self.campaign_id, call.invocation_id)
        with self.view() as view:
            assignment = call.assignment
            role = assignment.body["role"]
            purpose = judgment_purpose(view, assignment)
            assessments = [
                view.read(Ref.from_record(ref), "parent_assessment")
                for ref in local.body["assessment_refs"]
            ]
            measure = (
                assignment.body["acceptance_measure_ref"]
                if role in {"parts", "designer"}
                else assignment.body["local_measure_ref"]
            )
            checks = [
                view.read(ref, "check")
                for ref in authorized_check_refs(view, self.policy, assignment)
            ]
            relevant = [
                check
                for check in checks
                if check.body["measure_ref"] == measure
                and check.body["purpose"] == purpose
                and check.body["requirement_key"]
                in assignment.body["scope_requirement_keys"]
            ]
            states = {
                key: status for key, (_, status) in current_check_states(view).items()
            }
            requirements = [
                row
                for row in self.requirements
                if row["requirement_key"] in assignment.body["scope_requirement_keys"]
            ]
            local_ids = {row["local_id"] for row in requirements}
            static_ids = {
                row["requirement_key"]
                for row in requirements
                if row["evidence_scope"] == "static_materialization"
            }
            handoff = self.materialization_handoff
            static_checks = [
                row for row in handoff["checks"] if row["requirement_id"] in static_ids
            ]
            static_check_ids = {row["check_id"] for row in static_checks}
            covered = {
                check.body["requirement_key"]
                for check in relevant
                if check.body["mandatory"]
            }
            missing_measures = sorted(
                set(assignment.body["contribution_requirement_keys"]) - covered
            )
            child_reports = [
                row.record
                for row in view.entries("report")
                if view.read(
                    Ref.from_record(row.record.body["assignment_ref"]), "assignment"
                ).body["parent_assignment_ref"]
                == assignment.ref.as_record()
            ][-8:]
            child_decisions = [
                {
                    "report_ref": report.ref.as_record(),
                    "decision": decision_context(view, Ref.from_record(ref)),
                }
                for report in child_reports
                for ref in report.body["decision_request_refs"]
            ]
            parent_evaluation = (
                evaluation_availability(
                    resolve_evaluations(view, self.policy, assignment, purpose)
                )
                if role in {"parts", "designer"}
                else None
            )
            measure_proposals = {
                row.record.artifact_id.value: row.record
                for row in view.entries("measure_proposal")
                if row.record.body["assignment_ref"] == assignment.ref.as_record()
            }
            for report in child_reports:
                for reference in report.body["measure_proposal_refs"]:
                    record = view.read(Ref.from_record(reference), "measure_proposal")
                    measure_proposals[record.artifact_id.value] = record
            source_admissions = relevant_sources(view, measure)
            source_rejected = bool(
                source_admissions and source_admissions[-1].status == "rejected"
            )
            investigations = visible_findings(view, assignment)
            context = {
                "assignment": assignment.as_record(),
                "test_history": assigned_history(
                    view, call.invocation_id, history_query
                ),
                "goal": self.store.evidence.reference(
                    Ref.from_record(assignment.body["goal_record_ref"]), self.duet_id
                ),
                "requirements": requirements,
                "materialization_baseline": {
                    "handoff_ref": {
                        key: handoff[key] for key in ("artifact_id", "content_hash")
                    },
                    "candidate_ref": {
                        key: handoff["candidate"][key]
                        for key in ("artifact_id", "content_hash")
                    },
                    "scope": handoff["scope"],
                    "checks": static_checks,
                    "observations": [
                        row
                        for row in handoff["observations"]
                        if row["check_id"] in static_check_ids
                    ],
                    "progress": handoff["progress"],
                    "progress_definition": handoff["progress_definition"],
                    "check_definitions": [
                        row
                        for row in handoff["check_definitions"]
                        if row["definition_id"]
                        in {check["definition_id"] for check in static_checks}
                    ],
                    "limitations": handoff["limitations"],
                },
                "part_dependencies": [
                    row
                    for row in handoff["episode_dependencies"]
                    if row["parent_local_id"] in local_ids
                    or row["child_local_id"] in local_ids
                ],
                "measurement_gaps": missing_measures,
                "investigation_needs": catalog(view, self.policy, assignment),
                "investigation_findings": investigations,
                "investigation_reference_data": reference_data(
                    view, self.policy, assignment, investigations
                ),
                "child_reports": [report_overview(report) for report in child_reports],
                "child_decisions": child_decisions,
                "evaluation_availability": parent_evaluation,
                "whole_build_readiness": (
                    root_readiness(view, assignment, self.policy)
                    if assignment.body["parent_assignment_ref"] is None
                    else None
                ),
                **context_bundle(view, assignment, child_reports),
                "measure_proposals": [
                    record.as_record() for record in measure_proposals.values()
                ],
                "measure_controls": control_context(
                    view, (record.ref for record in measure_proposals.values())
                ),
                "admitted_measures": [
                    item.as_record() for item in admitted_measures(view, assignment)
                ],
                "measure_admission_policy": self.policy.get("measure_admission"),
                "measure_groups": [
                    {"measure_ref": ref.as_record(), "definition": group_definition(*purposes)}
                    for ref, purposes in declarations(view, self.policy).items()
                ],
                "measure_needs": measure_needs(view, assignment, self.policy),
                **measure_design_context(view, assignment, self.policy),
                "assigned_prerequisites": assigned_context(view, assignment),
                **grounding_context(view, assignment, self.policy),
                "source_admissions": [
                    {
                        "source_ref": row.record.ref.as_record(),
                        "admitted": row.record.body["admitted"],
                        "receipt": self.store.evidence.reference(
                            Ref.from_record(row.record.body["build_receipt_ref"]),
                            self.duet_id,
                        ),
                    }
                    for row in source_admissions[-1:]
                ],
                "materialization_findings": [
                    row
                    for row in self.materialization["deficits"]
                    if row["deficit"]["episode_local_id"] is None
                    or row["deficit"]["episode_local_id"]
                    in {item["local_id"] for item in requirements}
                ],
                "available_measures": [
                    {
                        "check_ref": check.ref.as_record(),
                        "measure_ref": _thaw_json(check.body["measure_ref"]),
                        "purpose": check.body["purpose"],
                        "evidence_kind": check.body["evidence_kind"],
                        "requirement_key": check.body["requirement_key"],
                    }
                    for check in checks
                    if check.body["requirement_key"]
                    in assignment.body["scope_requirement_keys"]
                ],
                "state": local.as_record(),
                "candidate": view.candidate.as_record(),
                "candidate_materialization": edit_context(
                    view, self.policy, assignment
                ),
                "checks": [check.as_record() for check in relevant],
                "baseline_required": not source_rejected
                and (parent_evaluation is None or parent_evaluation["executable"])
                and any(
                    states.get(check.artifact_id.value) not in {"pass", "fail"}
                    for check in relevant
                ),
                "evaluation_purpose": purpose,
                "proposal_schemas": proposal_schemas(role),
                "parent_assessments": [
                    {
                        "assessment": item.as_record(),
                        "current_status": assessment_status(view, item),
                    }
                    for item in assessments
                ],
                "prerequisite_assessments": [
                    {
                        "assessment": item.as_record(),
                        "current_status": prerequisite_status(view, item),
                    }
                    for ref in local.body["prerequisite_assessment_refs"]
                    for item in (
                        view.read(Ref.from_record(ref), "prerequisite_assessment"),
                    )
                ],
                "source_files": {},
                "source_kinds": {},
                "last_feedback": feedback(self, call.feedback_ref)
                if call.feedback_ref is not None
                else None,
                "observations": [
                    row.record.as_record()
                    for row in view.entries("check_state")
                    if row.key in {check.artifact_id.value for check in relevant}
                ],
                "recent_units": [
                    view.read(Ref.from_record(ref)).as_record()
                    for ref in local.body["recent_unit_refs"]
                ],
                "conflicts": [
                    view.read(Ref.from_record(ref)).as_record()
                    for ref in local.body["conflict_refs"]
                ],
                "lessons": [
                    view.read(Ref.from_record(ref)).as_record()
                    for ref in local.body["applicable_lesson_refs"]
                ],
                "design_plans": [
                    row.record.as_record()
                    for row in view.entries("plan")
                    if row.record.body["assignment_ref"]
                    in (
                        assignment.ref.as_record(),
                        assignment.body["parent_assignment_ref"],
                    )
                ],
            }
            instrument_context(view, assignment, context)
            # The model receives the assigned candidate, never arbitrary host paths.
            candidate = view.candidate
            readable = set()
            if role in {"designer", "implementer"}:
                readable.update(assignment.body["writable_paths"])
                for check in relevant:
                    readable.update(check.body["dependency_paths"] or ())
            status = view.entry("invocation", call.invocation_id.value).status
        for path in sorted(readable.intersection(candidate.body["files"])):
            context["source_files"][path] = self.store.evidence.builds.read_blob(
                candidate.body["files"][path]
            ).decode("utf-8")
        for local_id, path in context["candidate_materialization"][
            "source_paths"
        ].items():
            if path in context["source_files"]:
                context["source_kinds"][path] = source_kind(handoff, local_id)
        return {
            "context": context,
            "disposition": "continuing" if status == "active" else status,
        }

    def reply(self, call, /, *, proceed=True, **values):
        return {**self.snapshot(call), "proceed": proceed, **values}

    def _context(self, call, episode_id, payload):
        exact(
            payload,
            {"role"}
            | ({"test_history_query"} if "test_history_query" in payload else set()),
            "refinement context",
        )
        if payload["role"] != call.assignment.body["role"]:
            raise ValueError("worker requested another role's context")
        return self.snapshot(call, history_query=payload.get("test_history_query"))

    def _begin_unit(self, call, episode_id, payload):
        self._context(call, episode_id, payload)
        if call.unit_id is not None:
            raise ValueError("refinement invocation already has an open unit")
        with self.view() as view:
            if view.entry("invocation", call.invocation_id.value).status != "active":
                raise ValueError("only the active invocation may open a unit")
            ordinal = sum(
                row.record.invocation_id == call.invocation_id
                for row in view.entries("unit")
            )
            call.candidate_before = view.candidate.ref
        call.unit_id = content_id(
            "refinement_unit",
            {
                "run_id": self.registration.logical_run_id.value,
                "invocation_id": call.invocation_id.value,
                "ordinal": ordinal,
            },
        )
        return self.reply(call, unit_id=call.unit_id.value)

    @staticmethod
    def _require_unit(call, payload):
        if call.unit_id is None or payload.get("unit_id") != call.unit_id.value:
            raise ValueError("request does not belong to the open refinement unit")

    def _propose(self, call, episode_id, payload):
        from .runtime_proposals import admit_proposal

        self._require_unit(call, payload)
        exact(
            payload,
            {"unit_id", "task", "raw_response", "producer_call_id"},
            "refinement proposal",
        )
        events = self.store.evidence.runs.read_execution_prefix(
            self.registration.run_id
        )
        producers = [
            event
            for event in events
            if event.kind is RunEventKind.MODEL_RESPONDED
            and event.origin is RunEventOrigin.HOST
            and event.episode_id == episode_id
            and event.payload.get("producer_call_id") == payload["producer_call_id"]
        ]
        if (
            len(producers) != 1
            or producers[0].payload["response_text"] != payload["raw_response"]
        ):
            raise ValueError("proposal is not this Episode's committed model response")
        producer = producers[0]
        audit = {
            "run_id": producer.run_id.value,
            "event": producer.as_record(),
            "task": payload["task"],
        }
        ref = self.put_data("model_proposal", audit)
        # Malformed or inadmissible output remains evidence and earns no credit.
        try:
            proposal = _parse_json(payload["raw_response"])
            return admit_proposal(self, call, payload["task"], proposal, ref)
        except (TypeError, ValueError, KeyError, DuetNotFoundError) as exc:
            call.feedback_ref = self.put_data(
                "proposal_rejection",
                {
                    "proposal_ref": ref.as_record(),
                    "reason": str(exc),
                    "assignment_ref": call.assignment.ref.as_record(),
                    "task": payload["task"],
                },
            )
            return self.reply(call, proceed=False, rejection=str(exc))

    def put_data(self, kind, value):
        return self.store.put_data(self.duet_id, kind, value)

    def _prepare_child(self, call, episode_id, payload):
        from .runtime_proposals import verification_assignment

        self._require_unit(call, payload)
        exact(payload, {"unit_id", "selection"}, "refinement child selection")
        selection = payload["selection"]
        role = selection["role"]
        if role not in ROLES[call.assignment.body["role"]].children:
            raise ValueError("role cannot create this child")
        if "purpose" in selection:
            if role != "verify":
                raise ValueError(
                    "only fixed independent verification has an automatic assignment"
                )
            selection = verification_assignment(self, call, selection["purpose"])
        with self.view() as view:
            child = view.entry("invocation", selection["invocation_id"])
            if (
                child.status != "ready"
                or child.record.body["parent_assignment_ref"]
                != call.assignment.ref.as_record()
            ):
                raise ValueError("child is not a ready assignment of this parent")
            child_assignment = child.record
        node = self.nodes[role]
        parent_node = self.nodes_by_grain[call.path[-1][0]]
        edge = self.edges[(parent_node.local_id, role)]
        if edge.child_local_id != node.local_id:
            raise ValueError("child differs from the approved runtime slot")
        goal_data = self.store.evidence.reference(
            Ref.from_record(child_assignment.body["goal_record_ref"]), self.duet_id
        )
        objective = {
            "role": role,
            "assignment_id": child_assignment.artifact_id.value,
            "goal": goal_data,
        }
        goal = EpisodeGoal.child(
            call.goal, objective=objective, result_contract=RESULT_PAYLOAD.as_record()
        )
        path = call.path + ((node.grain_name, child.key),)
        child_id = EpisodeRef(
            run_id=self.registration.logical_run_id.value, path=path
        ).episode_id
        self.pending[child_id] = Invocation(
            OpaqueId(child.key), child_assignment, path, goal
        )
        return self.reply(
            call,
            call={
                "role": role,
                "grain": node.grain_name,
                "goal": objective,
                "invocation_id": child.key,
                "assignment_id": child_assignment.artifact_id.value,
                "campaign_id": self.campaign_id.value,
                "result_channel_ids": list(node.result_channel_ids),
            },
        )

    def _enter_child(self, call, episode_id, payload):
        exact(payload, {"request", "goal", "invocation"}, "refinement child entry")
        descriptor = payload["invocation"]
        child_id = descriptor["child_episode_id"]
        child = self.pending.get(child_id)
        if child is None and child_id in self.calls:
            entered = self.calls[child_id]
            if (
                entered.path[:-1] != call.path
                or entered.request.as_record() != payload["request"]
                or entered.goal.as_record() != payload["goal"]
            ):
                raise ValueError("runtime guard differs from the admitted child call")
            with self.view() as view:
                if (
                    view.entry("invocation", entered.invocation_id.value).status
                    != "active"
                    or view.entry("invocation", call.invocation_id.value).status
                    != "waiting"
                ):
                    raise ValueError("runtime guard is not for the current child")
            return {"admitted": True}
        if child is None or child.path[:-1] != call.path:
            raise ValueError("no pending child for this parent")
        if payload["goal"] != child.goal.as_record():
            raise ValueError("worker changed the admitted child goal")
        request = payload["request"]
        address = ParentRequestAddress(
            request["request_id"],
            episode_id.value,
            child_id,
            child.goal.goal_id,
            f"refinement.{child.assignment.body['role']}",
        )
        admitted = admit_parent_request(request, address, REQUEST_PAYLOAD)
        if dict(admitted.artifact_ids_by_role) != {
            "campaign": (self.campaign_id.value,),
            "assignment": (child.assignment.artifact_id.value,),
            "invocation": (child.invocation_id.value,),
        }:
            raise ValueError("worker changed the admitted child assignment")
        self.commit(call, "enter_child", {"invocation_id": child.invocation_id.value})
        child.request = admitted
        self.calls[child_id] = child
        del self.pending[child_id]
        return {"admitted": True}

    def _receive_child(self, call, episode_id, payload):
        self._require_unit(call, payload)
        exact(
            payload,
            {"unit_id", "request", "result", "completion"},
            "refinement child return",
        )
        child = self.calls[payload["request"]["child_episode_id"]]
        if (
            child.path[:-1] != call.path
            or payload["request"] != child.request.as_record()
        ):
            raise ValueError("child result belongs to another parent")
        result = admit_child_result(
            payload["result"],
            child.request,
            self.nodes_by_grain[child.path[-1][0]].result_channel_ids,
            RESULT_PAYLOAD,
        )
        report = self.store.project(self.campaign_id, child.invocation_id)
        if (
            result.artifact_ids_by_role["report"] != (report.artifact_id.value,)
            or result.states["disposition"] != report.body["termination"]
            or any(
                ids != (report.artifact_id.value,)
                for ids in result.logical_identity_ids_by_channel.values()
            )
        ):
            raise ValueError("worker changed the host-derived child report")
        # The child is already closed. This is its ordinary return operation,
        # not another unit and not an opportunity to assign parent credit.
        child.unit_id = report.logical_unit_id or content_id(
            "refinement_return", report.ref.as_record()
        )
        self.commit(child, "return_child", {})
        child.unit_id = None
        with self.view() as view:
            status = view.entry("invocation", call.invocation_id.value).status
        return self.reply(call, proceed=status == "active")

    def _close_unit(self, call, episode_id, payload):
        self._require_unit(call, payload)
        exact(payload, {"unit_id"}, "refinement unit close")
        if call.assignment.body["role"] == "parts":
            self._resolve_joint_results(call)
        self.commit(
            call,
            "close_unit",
            {
                "candidate_before_ref": call.candidate_before.as_record(),
                "continuation_ref": None,
            },
        )
        with self.view() as view:
            receipts = [
                row.record
                for row in view.entries("unit")
                if row.record.logical_unit_id == call.unit_id
                and row.record.invocation_id == call.invocation_id
            ]
            receipt = receipts[-1]
            decision = view.read(
                Ref.from_record(receipt.body["continuation_ref"]), "continuation"
            )
        call.unit_id = None
        return {
            "receipt_ref": receipt.ref.as_record(),
            "disposition": receipt.body["disposition"],
            "stop": receipt.body["disposition"]
            in {"attained", "yield_exhausted_unresolved"},
            "measurement": receipt.as_record(),
            "numerical_decision": decision.as_record(),
        }

    def _resolve_joint_results(self, call):
        ready = []
        with self.view() as view:
            coordinations = {
                row.key: row.record for row in view.entries("coordination")
            }
            states = {row.key: row for row in view.entries("check_state")}
            for row in view.entries("conflict"):
                conflict = row.record
                if (
                    row.status != "decision_required"
                    or conflict.body["scope_owner_invocation_id"]
                    != call.invocation_id.value
                ):
                    continue
                coordination = coordinations.get(row.key)
                if coordination is None:
                    continue
                observations = [
                    states.get(key) for key in coordination.body["required_check_keys"]
                ]
                if not observations or any(
                    item is None or item.status != "pass" for item in observations
                ):
                    continue
                if all(
                    view.read(
                        Ref.from_record(item.record.body["request_ref"]), "evaluation"
                    ).body["candidate_ref"]
                    == view.candidate.ref.as_record()
                    for item in observations
                ):
                    ready.append(conflict.ref)
        for reference in ready:
            # Admission repeats the same-candidate/guard checks before changing
            # the shared conflict status. A child's success label is irrelevant.
            self.commit(
                call, "resolve_conflict", {"conflict_ref": reference.as_record()}
            )

    def _report(self, call, episode_id, payload):
        exact(payload, set(), "refinement report")
        report = self.store.project(self.campaign_id, call.invocation_id)
        if report.body["termination"] == "continuing":
            raise ValueError("an unresolved continuation cannot publish a final result")
        with self.view() as view:
            self.store._put(view.connection, self.duet_id, report)
        return {
            "report_id": report.artifact_id.value,
            "disposition": report.body["termination"],
        }

    def validate_return(self, terminal_status, typed_status):
        root = self.calls[self.root_id]
        expected_report = self.store.project(self.campaign_id, root.invocation_id)
        report = {
            "report_id": expected_report.artifact_id.value,
            "disposition": expected_report.body["termination"],
        }
        outcomes = {
            "attained": "succeeded",
            "yield_exhausted_unresolved": "blocked",
            "needs_parent_decision": "blocked",
        }
        expected = outcomes.get(report["disposition"])
        if (
            expected is None
            or terminal_status != expected
            or typed_status["outcome"] != expected
            or typed_status["root_episode_id"] != self.root_id
            or typed_status["workflow_result"] != report
        ):
            raise ValueError(
                "worker return differs from the host's root judgment and disposition"
            )
        with self.view() as view:
            view.read(expected_report.ref, "parent_report")
