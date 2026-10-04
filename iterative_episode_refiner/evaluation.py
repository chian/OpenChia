"""The refiner's single validation connection to the existing Builder and executor.

No generated code runs in this host. No subprocess runner, synthetic Run events,
or replay entry point lives here. All roles submit requests through this service;
the native-workflow route runs the approved target root with no refiner privileges.
Additional instruments belong to the same shared validation service, not role-
specific runners.
"""

import asyncio

from agent.duet_contracts import content_id
from agent.episode_contracts import OpaqueId
from episode_runtime.contracts import RuntimePolicy
from episode_runtime.testing.observations import is_verified_run_path
from function_library.epistemic_contract import exact

from .candidate_source import admit_candidate
from .records import EvidenceRef, Ref


class RefinementEvaluations:
    def __init__(
        self,
        *,
        builder,
        executor,
        runtime_policy=None,
        target_launch_ref=None,
        http_credentials=None,
        progress_callback=None,
    ):
        self.builder = builder
        self.executor = executor
        self.runtime_policy = runtime_policy or RuntimePolicy()
        self.target_launch_ref = target_launch_ref
        self.http_credentials = http_credentials
        self.progress_callback = progress_callback

    def _requests(self, session, call, payload):
        from .evaluation_plan import resolve_evaluations

        investigation = call.assignment.body["role"] in {"support", "question"}
        fields = {"unit_id", "purpose"}
        if investigation:
            fields.add("proposal_ref")
        exact(payload, fields, "native workflow evaluation")
        purpose = payload["purpose"]
        with session.view() as view:
            candidate = view.candidate
            selected = None
            if investigation:
                from .investigation import selected_checks

                proposal = view.data(Ref.from_record(payload["proposal_ref"]))
                exact(
                    proposal,
                    {
                        "assignment_ref",
                        "producer_ref",
                        "invocation_id",
                        "logical_unit_id",
                        "check_keys",
                    },
                    "investigation choice",
                )
                if (
                    proposal["assignment_ref"] != call.assignment.ref.as_record()
                    or proposal["invocation_id"] != call.invocation_id.value
                    or proposal["logical_unit_id"] != call.unit_id.value
                ):
                    raise ValueError(
                        "investigation choice belongs to another assignment or unit"
                    )
                selected = selected_checks(
                    view, session.policy, call.assignment, proposal["check_keys"]
                )
            plans = resolve_evaluations(
                view,
                session.policy,
                call.assignment,
                purpose,
                selected=selected,
            )
        requests = []
        for plan in plans:
            checks = plan["checks"]
            request = session.record(
                call,
                "evaluation",
                {
                    **plan["binding"],
                    "availability": plan["availability"],
                    **(
                        {"selection_check_keys": plan["selection_check_keys"]}
                        if plan["selection_check_keys"] is not None
                        else {}
                    ),
                    "candidate_ref": candidate.ref.as_record(),
                    "check_keys": [check.artifact_id.value for check in checks],
                    "environment_ref": session.contract.body["environment_ref"],
                    "parent_operation_id": content_id(
                        "refinement_validation",
                        {
                            "unit": call.unit_id.value,
                            "candidate": candidate.ref.as_record(),
                            "purpose": purpose,
                        },
                    ).value,
                },
            )
            session.commit(call, "request_evaluation", {"request": request.as_record()})
            requests.append((request, checks))
        return candidate, requests

    def _record_source(self, session, call, request, candidate, receipt):
        receipt_ref = session.put_data("validation_build_receipt", receipt.as_record())
        source = session.record(
            call,
            "evaluation_source",
            {
                "request_ref": request.ref.as_record(),
                "candidate_ref": candidate.ref.as_record(),
                "build_receipt_ref": receipt_ref.as_record(),
                "admitted": receipt.materialized,
            },
        )
        session.commit(call, "record_evaluation_source", {"source": source.as_record()})
        return receipt_ref

    def _bind(
        self,
        session,
        call,
        request,
        candidate,
        receipt_ref,
        registration,
        *,
        stage=None,
    ):
        binding = session.record(
            call,
            "evaluation_run",
            {
                "request_ref": request.ref.as_record(),
                "candidate_ref": candidate.ref.as_record(),
                "build_receipt_ref": receipt_ref.as_record(),
                "registration": registration.as_record(),
                **(stage or {}),
            },
        )
        session.commit(call, "bind_evaluation_run", {"binding": binding.as_record()})
        return binding

    def _observe(self, session, call, request, registration, evidence, checks):
        events = session.store.evidence.runs.read_audit_log(registration.run_id)
        terminal = next(
            event for event in events if event.event_id == evidence.terminal_event_id
        )
        for check in checks:
            references = ()
            if evidence.terminal_status.value == "succeeded" or is_verified_run_path(
                check.body["observation_path"]
            ):
                references = (
                    EvidenceRef(
                        "run_audit",
                        registration.run_id,
                        terminal.event_id,
                        terminal.event_hash,
                        check.body["observation_path"],
                    ),
                )
            session.commit(
                call,
                "observe",
                {
                    "request_ref": request.ref.as_record(),
                    "run_id": registration.run_id.value,
                    "execution_ref": Ref(
                        evidence.evidence_id, evidence.content_hash
                    ).as_record(),
                    "check_key": check.artifact_id.value,
                },
                evidence=references,
            )

    def _observe_materialization(self, session, call, request, receipt_ref, checks):
        for check in checks:
            session.commit(
                call,
                "observe_materialization",
                {
                    "request_ref": request.ref.as_record(),
                    "check_key": check.artifact_id.value,
                },
                evidence=(
                    EvidenceRef(
                        "duet_artifact",
                        OpaqueId(session.duet_id),
                        receipt_ref.artifact_id,
                        receipt_ref.content_hash,
                        "",
                    ),
                ),
            )

    @staticmethod
    def _source_key(session, request):
        from .instrument_builds import selected_entry

        with session.view() as view:
            instrument = view.data(Ref.from_record(request.body["harness_ref"]))
            if instrument.get("execution_kind") == "reference_workflow":
                return ("reference", Ref.from_record(instrument["reference_ref"]))
            entry = selected_entry(view, request.body)
            return entry["spec_ref"]["artifact_id"] if entry else "target"

    async def evaluate(self, session, call, payload):
        if self.progress_callback is not None:
            self.progress_callback("validating")
        try:
            return await self._evaluate(session, call, payload)
        finally:
            if self.progress_callback is not None:
                self.progress_callback("refining")

    async def _evaluate(self, session, call, payload):
        if self.executor.run_store is not session.store.evidence.runs:
            raise ValueError("validation must use the campaign's existing RunStore")
        if "experiment_proposal_ref" in payload:
            from .evaluation_experiments import execute_experiment

            return await execute_experiment(self, session, call, payload)
        if call.assignment.body["role"] == "measure" and "proposal_ref" in payload:
            return await self._evaluate_measure(session, call, payload)
        candidate, requests = await asyncio.to_thread(
            self._requests, session, call, payload
        )
        available = [
            (request, checks)
            for request, checks in requests
            if request.body["availability"]["executable"]
        ]
        if not available:
            return await asyncio.to_thread(
                session.reply,
                call,
                proceed=False,
                evaluation_gaps=[request.as_record() for request, _ in requests],
            )
        receipts = {}
        evaluated = True
        admitted = True
        experiment_targets = []
        for request, checks in available:
            key = await asyncio.to_thread(self._source_key, session, request)
            if key not in receipts:
                receipts[key] = await admit_candidate(
                    session.store,
                    session.contract,
                    candidate,
                    self.builder,
                    request.body,
                )
            receipt = receipts[key]
            ready = await self._evaluate_request(
                session, call, request, candidate, checks, receipt
            )
            if isinstance(ready, dict):
                experiment_targets.append(ready)
                ready = False
            evaluated = evaluated and ready
            admitted = admitted and (
                receipt.materialized
                or not any(
                    check.body["evidence_kind"] == "execution" for check in checks
                )
            )
        return await asyncio.to_thread(
            session.reply,
            call,
            proceed=evaluated and len(available) == len(requests) and admitted,
            source_admitted=all(receipt.materialized for receipt in receipts.values()),
            experiment_targets=experiment_targets,
        )

    async def _evaluate_request(
        self, session, call, request, candidate, checks, receipt
    ):
        receipt_ref = await asyncio.to_thread(
            self._record_source, session, call, request, candidate, receipt
        )
        static_checks = [
            check
            for check in checks
            if check.body["evidence_kind"] == "materialization"
        ]
        runtime_checks = [
            check for check in checks if check.body["evidence_kind"] == "execution"
        ]
        await asyncio.to_thread(
            self._observe_materialization,
            session,
            call,
            request,
            receipt_ref,
            static_checks,
        )
        if not runtime_checks:
            return True
        if not receipt.materialized:
            return False
        from .evaluation_experiments import experiment_target

        return await asyncio.to_thread(
            experiment_target, self, session, call, request, receipt, runtime_checks
        )

    def _measure_jobs(self, session, call, payload):
        from .measure_admission import grounded_cases

        exact(payload, {"unit_id", "purpose", "proposal_ref"}, "measure evaluation")
        if payload["purpose"] != "adequacy":
            raise ValueError("EstablishMeasure must evaluate adequacy")
        with session.view() as view:
            proposal = view.read(
                Ref.from_record(payload["proposal_ref"]), "measure_proposal"
            )
            if proposal.body["assignment_ref"] != call.assignment.ref.as_record():
                raise ValueError("measure proposal belongs to another assignment")
            if proposal.body["oracle_kind"] != "independent_execution":
                return []
            cases, _, _ = grounded_cases(view, proposal, session.policy)
            return [
                (proposal.ref, grounding_ref, Ref.from_record(control_ref))
                for grounding_ref, grounding in cases
                for field in ("positive_control_refs", "negative_control_refs")
                for control_ref in grounding[field]
            ]

    def _bind_measure_control(self, session, call, job, registration, gap, *, experiment_ref=None):
        proposal_ref, grounding_ref, control_ref = job
        binding = session.record(
            call,
            "measure_control_run",
            {
                "proposal_ref": proposal_ref.as_record(),
                "grounding_ref": grounding_ref.as_record(),
                "control_ref": control_ref.as_record(),
                "registration": registration.as_record() if registration else None,
                "gap": gap,
                **({"experiment_ref": experiment_ref} if experiment_ref is not None else {}),
            },
        )
        session.commit(call, "bind_measure_control", {"binding": binding.as_record()})
        return binding

    def _observe_measure_control(self, session, call, binding, registration, evidence):
        references = ()
        if evidence.terminal_status.value == "succeeded":
            terminal = next(
                event
                for event in session.store.evidence.runs.read_audit_log(
                    registration.run_id
                )
                if event.event_id == evidence.terminal_event_id
            )
            references = (
                EvidenceRef(
                    "run_audit",
                    registration.run_id,
                    terminal.event_id,
                    terminal.event_hash,
                    "",
                ),
            )
        session.commit(
            call,
            "observe_measure_control",
            {
                "control_run_ref": binding.ref.as_record(),
                "run_id": registration.run_id.value,
                "execution_ref": Ref(
                    evidence.evidence_id, evidence.content_hash
                ).as_record(),
            },
            evidence=references,
        )

    async def _evaluate_measure(self, session, call, payload):
        from .measure_experiments import targets

        try:
            jobs = await asyncio.to_thread(self._measure_jobs, session, call, payload)
        except (ValueError, KeyError, TypeError):
            # The ordinary admission path records the exact unsupported proposal
            # as a rejection. No malformed proposal is executed as a control.
            return await asyncio.to_thread(self._admit_measure, session, call, payload)
        choices, gaps = await asyncio.to_thread(targets, self, session, call, jobs)
        if choices:
            return await asyncio.to_thread(session.reply, call, experiment_targets=choices, evaluation_gaps=gaps)
        return await asyncio.to_thread(self._admit_measure, session, call, payload)

    def _admit_measure(self, session, call, payload):
        from .measure_admission import definition

        exact(payload, {"unit_id", "purpose", "proposal_ref"}, "measure evaluation")
        if payload["purpose"] != "adequacy":
            raise ValueError("EstablishMeasure must evaluate adequacy")
        with session.view() as view:
            proposal = view.read(
                Ref.from_record(payload["proposal_ref"]), "measure_proposal"
            )
        measure_ref = session.put_data("grounded_measure", definition(proposal))
        session.commit(
            call,
            "admit_measure",
            {
                "proposal_ref": proposal.ref.as_record(),
                "measure_ref": measure_ref.as_record(),
            },
        )
        return session.reply(call)
