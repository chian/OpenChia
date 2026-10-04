"""Experiment dispatch through existing admission, executor and durable stores.

The dispatch marker is immutable and claims no liveness. Repeated submissions
inspect the same Run; they do not launch another process or award credit.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace

from agent.duet_contracts import canonical_json, content_id
from agent.episode_launch import resolve_launch
from agent.episode_launch_transport import LaunchModelTransport
from handoff_library import DuetLaunchAddress, admit_duet_launch_request

from ..broker import ScopedModelBroker
from ..contracts import RuntimePolicy
from ..http_broker import HttpxHostTransport, ScopedHttpBroker
from .inputs import workflow_template
from .execution import RunExecution, register_build
from .planning import preview_experiment
from ..records.experiments import artifact_fields, read_record, read_reference


class ExperimentService:
    def __init__(
        self,
        *,
        artifacts,
        builds,
        runs,
        executor=None,
        http_credentials=None,
        runtime_policy=None,
        duet_binding=None,
        refinement_evaluations=None,
    ):
        if executor is not None and executor.run_store is not runs:
            raise ValueError("experiment executor must use the supplied RunStore")
        self.artifacts, self.builds, self.runs, self.executor = (
            artifacts,
            builds,
            runs,
            executor,
        )
        self.http_credentials = {} if http_credentials is None else http_credentials
        self.runtime_policy = runtime_policy or RuntimePolicy()
        self.duet_binding = duet_binding
        self.refinement_evaluations = refinement_evaluations
        self.execution = (
            None
            if executor is None
            else RunExecution(
                artifacts=artifacts, builds=builds, runs=runs, executor=executor,
                duet_binding=duet_binding, experiment_service=self,
            )
        )

    @staticmethod
    def history(artifacts, runs, *, duet_id, query, invocation=None):
        from ..records.catalog import history

        return history(
            artifacts, runs, duet_id=duet_id, query=query, invocation=invocation
        )

    @staticmethod
    def inventory(artifacts, runs, *, duet_id, source, query):
        from ..records.catalog import inventory

        return inventory(artifacts, runs, duet_id=duet_id, source=source, query=query)

    @staticmethod
    def read_observation(artifacts, runs, *, duet_id, measurement_ref, receipt):
        """Resolve only an exact observation retained in this owner's report.

        The report may bind a declared cross-Duet checker. Its single recorded
        observation grants no access to other Runs or arbitrary audit paths.
        This host read is not an additional worker operation.
        """
        from .observations import read_observation_receipt

        row = read_reference(artifacts, measurement_ref, duet_id)
        if row["kind"] not in {
            "experiment.measurement.v1", "experiment.measurement_attempt.v1",
        }:
            raise ValueError("Observation reading requires an exact measurement report.")
        if not isinstance(receipt, Mapping):
            raise ValueError("Observation receipt must be a typed reference record.")
        if not any(
            canonical_json(outcome.get("observed")) == canonical_json(receipt)
            and outcome["evidence_ref"] == receipt.get("evidence_ref")
            for outcome in row["record"]["outcomes"]
        ):
            raise ValueError("Observation is not retained in the authorized measurement report.")
        return read_observation_receipt(runs, receipt)

    @staticmethod
    def status(artifacts, runs, experiment_id):
        from .numerical import saved_result
        from .measurements import saved_measurements
        from .instruments import instrument_statuses

        numerical = saved_result(artifacts, experiment_id)
        if numerical is not None:
            return numerical
        row = read_record(artifacts, "dispatch", experiment_id=experiment_id)
        if row is None:
            return {
                "experiment_id": experiment_id,
                "execution_status": "not_dispatched",
                "candidate_verdict": "unmeasured",
            }
        binding = row["record"]
        status = RunExecution.status(artifacts, runs, binding["registration"]["run_id"])
        if status["execution_status"] == "not_dispatched":
            # Intent may have committed before execution admission. That is not
            # permission to restart or evidence that a process is running.
            status.update(
                execution_status="terminal_evidence_unavailable",
                limitations=[
                    "Experimental intent is recorded; no execution dispatch is recorded yet."
                ],
            )
        result = {
            **status,
            "experiment_id": experiment_id,
            "executed_build_receipt_ref": binding["spec"]["build_receipt_ref"],
            "mode": binding["spec"]["mode"],
            "scope": binding["plan"]["scope"],
            "unresolved_questions": binding["spec"]["unresolved_questions"],
            "instrument_runs": instrument_statuses(artifacts, runs, row),
        }
        measurement = saved_measurements(artifacts, experiment_id)
        if measurement is not None:
            result.update(
                candidate_verdict=measurement["candidate_verdict"],
                measurement=measurement,
            )
        continued = status["run_id"] != binding["registration"]["run_id"]
        refinement = read_record(
            artifacts, "refinement_result_attempt" if continued else "refinement_result",
            experiment_id=experiment_id,
            **({"run_id": status["run_id"]} if continued else {}),
        )
        if refinement is not None:
            projection = refinement["record"]
            result["refinement"] = {
                "result_ref": {"artifact_id": refinement["artifact_id"], "content_hash": refinement["content_hash"]},
                "campaign_ref": projection["campaign_ref"],
                "disposition": projection["disposition"],
                "build_status": projection["build_status"],
                "verification_gaps": projection["verification_gaps"],
            }
        return result

    def _prepare(self, spec):
        request = spec.as_record()
        plan = self.preview(spec)
        gaps = list(plan["gaps"])
        if gaps:
            return {**plan, "resolved": False, "gaps": gaps}, None
        inputs = self.builds.inspection_inputs_for_receipt(
            request["build_receipt_ref"]["artifact_id"]
        )
        from .subjects import resolve_subject

        subject = resolve_subject(request, inputs=inputs, artifacts=self.artifacts, builds=self.builds, runs=self.runs)
        source_owner = inputs.build_request.frozen_workflow.duet_id.value
        duet_id = source_owner if subject is None else subject["owner_duet_id"]
        source_duet = self.artifacts.get_duet(source_owner)
        approved_head = inputs.build_request.authority_approval.approval_id.value
        if source_duet is None or source_duet["authority_head_approval_id"] != approved_head:
            raise ValueError(
                "experiment build no longer matches its Duet authority head"
            )
        for approval in (
            inputs.build_request.authority_approval,
            inputs.build_request.workflow_approval,
        ):
            current = self.artifacts.get_approval(approval.approval_id.value)
            if (
                current is None
                or current.pop("revoked")
                or current != approval.as_record()
            ):
                raise ValueError(
                    "experiment build approval is missing, changed or revoked"
                )
        duet = self.artifacts.get_duet(duet_id)
        refiner_job = subject is not None and subject["kind"] == "refinement_job"
        launch = self.duet_binding if refiner_job else (
            self._resolve_live_launch(request, inputs, duet_id=duet_id)
            if request["mode"] in {"live_fresh", "live_saved"}
            else None
        )
        root = next(
            node
            for node in inputs.plan.nodes
            if node.local_id == inputs.plan.root_local_id
        )
        payload = (
            None
            if request["scope"]["kind"] == "component"
            else request["start"]["input_payload"] or None
        )
        if subject is not None and subject["kind"] in {"grounded_control", "refinement_job"}:
            payload = subject["launch_template"].as_record()
        elif request["start"]["kind"] == "saved_inputs":
            from .recordings import load_recording

            source, _ = load_recording(
                self.artifacts, self.runs, request["start"]["artifact_ref"], source_owner
            )
            payload = source.launch_request.as_record()
        template = workflow_template(inputs.build_request.frozen_workflow, payload)
        address = DuetLaunchAddress(
            content_id("launch_request", {"experiment_id": spec.experiment_id}).value,
            template.workflow_id,
            template.goal_id,
        )
        launch_request = admit_duet_launch_request(
            {**template.as_record(), "request_id": address.request_id},
            address,
            root.request_payload_contract,
        )
        registration, package = register_build(
            self.executor,
            self.builds,
            inputs,
            launch_request,
            self.runtime_policy,
            execution_scope=_run_scope(plan["execution_scope"]),
        )
        refinement_session = None
        if refiner_job:
            from .refinement_subjects import make_session

            refinement_session = make_session(self, subject, registration, package)
        if request["mode"] == "recorded":
            from .playback import execution_context, prepare_playback

            prepare_playback(
                self.artifacts,
                self.runs,
                request["recording_ref"],
                registration,
                execution_context(
                    registration,
                    environment_ref=request["environment_ref"],
                    launch_ref=request["launch_ref"],
                ),
            )
        binding = {
            "spec": request,
            "plan": plan,
            "registration": registration.as_record(),
        }
        artifact = artifact_fields(
            "dispatch",
            duet_id=duet_id,
            record=binding,
            experiment_id=spec.experiment_id,
        )
        artifacts = [artifact]
        if refiner_job:
            artifacts.append(artifact_fields(
                "refinement_job", duet_id=duet_id,
                campaign_id=subject["campaign_id"],
                record={"experiment_id": spec.experiment_id, "campaign_ref": subject["reference"], "starting_state": subject["starting_state"], "registration": registration.as_record()},
            ))
        created = self.artifacts.put_artifacts_with_events(
            artifacts=tuple(artifacts),
            events=(
                {
                    "event_type": "experiment_dispatched",
                    "provenance": "host_validation",
                    "record": {
                        "experiment_id": spec.experiment_id,
                        "run_id": registration.run_id.value,
                    },
                },
            ),
            idempotency_artifact_ids=tuple(item["artifact_id"] for item in artifacts),
            duet_id=duet_id,
            expected_state=duet["state"],
            expected_authority_head_approval_id=duet["authority_head_approval_id"],
        )
        return plan, (registration, inputs, launch, package, refinement_session) if created else None

    def preview(self, spec):
        return preview_experiment(
            spec, builds=self.builds, artifacts=self.artifacts, runs=self.runs,
            duet_binding=self.duet_binding, refinement_evaluations=self.refinement_evaluations,
        )

    def _resolve_live_launch(self, request, inputs, *, duet_id=None):
        launch_record = read_reference(
            self.artifacts,
            request["launch_ref"],
            duet_id or inputs.build_request.frozen_workflow.duet_id.value,
        )["record"]
        if set(launch_record) != {"requested_spec", "resolved_spec", "sources"}:
            raise ValueError(
                "launch_ref must name a resolved launch; use openchia test register-launch"
            )
        launch = resolve_launch(launch_record["requested_spec"], frozen_record=launch_record)
        if launch.record != launch_record:
            raise ValueError(
                "launch settings changed; register a new launch and fork the experiment"
            )
        from episode_builder.planner import required_model_types

        required = set()
        for node in inputs.plan.nodes:
            required.update(required_model_types(node.prompt_specs, node.selected_function_bindings))
        missing = required - launch.model_slot_catalog().keys()
        if missing:
            raise ValueError(
                f"approved launch lacks required model slots: {sorted(missing)}"
            )
        from agent.episode_launch_host import resolve_approved_launch

        resolve_approved_launch(
            self.artifacts,
            duet_id or inputs.build_request.frozen_workflow.duet_id.value,
            configuration_hash=launch.configuration_hash,
            model_types=required,
            frozen_record=launch_record,
        )
        return launch

    async def run(self, spec):
        if spec.as_record()["mode"] == "numerical":
            return await asyncio.to_thread(self._numerical, spec)
        if self.executor is None:
            raise ValueError("candidate execution requires an admitted Run executor")
        prior = await asyncio.to_thread(
            self.status, self.artifacts, self.runs, spec.experiment_id
        )
        if prior["execution_status"] != "not_dispatched":
            return await self._finish_measurement(spec.experiment_id, prior)
        plan, prepared = await asyncio.to_thread(self._prepare, spec)
        if not plan["resolved"]:
            return {
                "experiment_id": spec.experiment_id,
                "execution_status": "unavailable",
                "candidate_verdict": "unmeasured",
                "plan": plan,
            }
        if prepared is None:
            return await asyncio.to_thread(
                self.status, self.artifacts, self.runs, spec.experiment_id
            )
        registration, inputs, launch, package, refinement_session = prepared
        binding = await asyncio.to_thread(
            read_record, self.artifacts, "dispatch", experiment_id=spec.experiment_id
        )
        await self._execute_registered(
            registration,
            inputs,
            launch,
            package,
            {
                "artifact_id": binding["artifact_id"],
                "content_hash": binding["content_hash"],
            },
            launch_id=spec.experiment_id,
            refinement_session=refinement_session,
        )
        result = await asyncio.to_thread(
            self.status, self.artifacts, self.runs, spec.experiment_id
        )
        return await self._finish_measurement(spec.experiment_id, result)

    async def _execute_registered(
        self, registration, inputs, launch, package, intent_ref, *, launch_id, refinement_session=None
    ):
        def record_attempt(record):
            self.artifacts.append_event(
                duet_id=registration.duet_id.value,
                event_type="model_launch_call",
                provenance="host_validation",
                record=record,
            )

        from agent.duet_episode_transport import DuetEpisodeBinding

        if isinstance(launch, DuetEpisodeBinding) and refinement_session is None:
            raise ValueError("Refiner execution requires its validated pre-dispatch host session.")
        transport = launch.transport(record_attempt=record_attempt) if isinstance(launch, DuetEpisodeBinding) else (
            None
            if launch is None
            else LaunchModelTransport(
                launch, launch_id=launch_id, record_attempt=record_attempt
            )
        )
        cancelled = False
        try:
            evidence = await self.execution.execute(
                registration=registration,
                source_package_path=package,
                intent_ref=intent_ref,
                model_broker=None
                if transport is None
                else ScopedModelBroker.from_plan(transport, inputs.plan),
                http_broker=None
                if transport is None
                else ScopedHttpBroker(
                    policy=registration.egress_policy,
                    credentials=self.http_credentials,
                    transport=HttpxHostTransport(),
                    max_frame_bytes=registration.runtime_policy.max_frame_bytes,
                ),
                refinement_session=refinement_session,
            )
        except asyncio.CancelledError:
            if refinement_session is None:
                raise
            from ..store import RunStoreNotFound

            # Native executors persist cancellation and re-raise. Preserve the
            # same typed last-known refiner report as other terminal outcomes,
            # then propagate cancellation; never turn it into completion.
            try:
                evidence = await asyncio.to_thread(self.runs.read_evidence, registration.run_id)
            except RunStoreNotFound:
                raise asyncio.CancelledError from None
            cancelled = True
        if refinement_session is not None:
            from iterative_episode_refiner.finalization import finalize_result
            from iterative_episode_refiner.handoff import attach_review
            from ..records.experiments import put_record

            result = await asyncio.to_thread(finalize_result, refinement_session, evidence)
            result = await asyncio.to_thread(attach_review, refinement_session, result)
            await asyncio.to_thread(
                put_record, self.artifacts,
                "refinement_result_attempt" if registration.resume_from is not None else "refinement_result",
                experiment_id=launch_id,
                **({"run_id": registration.run_id.value} if registration.resume_from is not None else {}),
                duet_id=refinement_session.duet_id, record=result.as_record(),
            )
        if cancelled:
            raise asyncio.CancelledError

    def _prepare_continuation(self, experiment_id, resume_from):
        from ..continuation import InterruptedRunRef
        from ..records.experiments import execution_attempts, read_run_intent
        from .contracts import ExperimentSpec
        from .refinement_subjects import make_session
        from .subjects import resolve_subject

        reference = InterruptedRunRef.from_record(resume_from)
        if reference != InterruptedRunRef.from_run(self.runs, reference.run_id):
            raise ValueError("continuation must name the exact final interruption evidence")
        previous = self.runs.read_registration(reference.run_id)
        attempts = execution_attempts(self.artifacts, self.runs, reference.run_id.value)
        if not attempts:
            raise ValueError("continuation requires an existing shared execution dispatch")
        dispatch = read_record(self.artifacts, "dispatch", experiment_id=experiment_id)
        if dispatch is None:
            raise ValueError("continuation requires its owning experiment")
        spec = ExperimentSpec.from_record(dispatch["record"]["spec"])
        intent_ref = attempts[0]["record"]["intent_ref"]
        intent = read_run_intent(self.artifacts, intent_ref, previous)
        expected_ref = {"artifact_id": dispatch["artifact_id"], "content_hash": dispatch["content_hash"]}
        launch_request = spec.as_record()
        launch_id, mode = experiment_id, launch_request["mode"]
        if intent["kind"] == "experiment.instrument.v1":
            from .instruments import _declared

            if intent["record"]["experiment_ref"] != expected_ref:
                raise ValueError("continued checker belongs to another experiment")
            instrument = _declared(dispatch["record"]).get(intent["record"]["instrument_id"])
            if instrument is None:
                raise ValueError("continued checker is absent from the frozen measurement plan")
            mode = instrument["mode"]
            launch_request = {**launch_request, "launch_ref": instrument["launch_ref"]}
            launch_id = f"{experiment_id}:{instrument['instrument_id']}"
        elif intent["kind"] != "experiment.dispatch.v1" or intent_ref != expected_ref:
            raise ValueError("continued Run is not this experiment's target or declared checker")
        if mode not in {"live_fresh", "live_saved"}:
            raise ValueError("continuing this recorded/numerical mode is unsupported; it cannot switch to live execution")
        selected = next((row for row in attempts if row["record"]["registration"]["run_id"] == reference.run_id.value), None)
        if selected is None:
            raise ValueError("interrupted Run is absent from the exact execution lineage")
        if attempts[-1] is not selected:
            return None  # This exact predecessor already has its one successor.
        registration = replace(previous, resume_from=reference)
        inputs = self.builds.inspection_inputs_for_receipt(registration.build_receipt_id)
        package = self.builds.verify_source_package(inputs.manifest)
        subject = None
        if intent["kind"] == "experiment.dispatch.v1":
            subject = resolve_subject(spec.as_record(), inputs=inputs, artifacts=self.artifacts, builds=self.builds, runs=self.runs)
        refiner_job = subject is not None and subject["kind"] == "refinement_job"
        launch = self.duet_binding if refiner_job else self._resolve_live_launch(launch_request, inputs, duet_id=dispatch["duet_id"])
        session = make_session(self, subject, registration, package) if refiner_job else None
        return registration, inputs, launch, package, intent_ref, launch_id, session

    async def continue_run(self, *, experiment_id, resume_from):
        """Continue the same experiment and expectations, not a changed candidate."""
        from ..continuation import InterruptedRunRef
        from ..records.experiments import execution_attempts
        from agent.episode_contracts import OpaqueId

        if self.executor is None:
            raise ValueError("continuation requires the existing admitted Run executor")
        reference = InterruptedRunRef.from_record(resume_from)
        attempts = await asyncio.to_thread(
            execution_attempts, self.artifacts, None, reference.run_id
        )
        history = tuple(OpaqueId(row["record"]["registration"]["run_id"]) for row in attempts)
        # Selecting immutable histories for reuse is not admission. Preparation
        # and execution still verify every linkage and current authority.
        with self.runs.terminal_snapshot_scope(history):
            prepared = await asyncio.to_thread(self._prepare_continuation, experiment_id, resume_from)
            if prepared is not None:
                registration, inputs, launch, package, intent_ref, launch_id, session = prepared
                await self._execute_registered(
                    registration, inputs, launch, package, intent_ref,
                    launch_id=launch_id, refinement_session=session,
                )
            result = await asyncio.to_thread(self.status, self.artifacts, self.runs, experiment_id)
            return await self._finish_measurement(experiment_id, result)

    async def continue_interrupted(self, *, experiment_id):
        """Recover terminal publication, then continue the latest exact attempt.

        A terminal journal entry is not itself proof that its worker stopped.
        Publication recovery and ordinary continuation both require the existing
        executor's exact process-identity check.
        """
        from ..continuation import InterruptedRunRef
        from ..contracts import RunRegistration
        from ..executor_lifecycle import verify_stopped_executor
        from ..records.experiments import execution_attempts

        dispatch = await asyncio.to_thread(
            read_record, self.artifacts, "dispatch", experiment_id=experiment_id
        )
        if dispatch is None or self.executor is None:
            raise ValueError("continuation requires an existing experiment and executor")
        attempts = await asyncio.to_thread(
            execution_attempts, self.artifacts, None,
            dispatch["record"]["registration"]["run_id"],
        )
        if not attempts:
            raise ValueError("experiment has no admitted execution to continue")
        registrations = tuple(
            RunRegistration.from_record(row["record"]["registration"]) for row in attempts
        )
        registration = registrations[-1]
        claim = await asyncio.to_thread(self.runs.read_claim, registration.run_id)
        await verify_stopped_executor(self.executor, claim)
        # This existing store method only publishes artifacts for an already
        # committed terminal head. It never invents a terminal state.
        with self.runs.terminal_snapshot_scope(item.run_id for item in registrations):
            await asyncio.to_thread(self.runs.complete_terminal_publication, registration.run_id)
            reference = await asyncio.to_thread(InterruptedRunRef.from_run, self.runs, registration.run_id)
            return await self.continue_run(experiment_id=experiment_id, resume_from=reference.as_record())

    async def _finish_measurement(self, experiment_id, result):
        if "evidence_ref" in result:
            from .measurements import measure_execution
            from .instruments import run_instruments

            instrument_runs = await run_instruments(self, experiment_id)
            if any(
                row["execution_status"] == "terminal_evidence_unavailable"
                for row in instrument_runs
            ):
                return {**result, "instrument_runs": instrument_runs}
            measurement = await asyncio.to_thread(
                measure_execution, self.artifacts, self.runs, experiment_id
            )
            return {
                **result,
                "candidate_verdict": measurement["candidate_verdict"],
                "measurement": measurement,
                "instrument_runs": instrument_runs,
            }
        return result

    def _numerical(self, spec):
        from .numerical import evaluate_numerical, saved_result

        prior = saved_result(self.artifacts, spec.experiment_id)
        if prior is not None:
            return prior
        plan = preview_experiment(
            spec, builds=self.builds, artifacts=self.artifacts, runs=self.runs
        )
        if not plan["resolved"]:
            return {
                "experiment_id": spec.experiment_id,
                "execution_status": "unavailable",
                "candidate_verdict": "unmeasured",
                "plan": plan,
            }
        return evaluate_numerical(
            spec,
            builds=self.builds,
            artifacts=self.artifacts,
            runs=self.runs,
            plan=plan,
        )


def _run_scope(value):
    from ..scoped import scope_from_record

    return scope_from_record(value)
