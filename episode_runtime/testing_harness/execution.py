"""The shared admitted-Run path for experiments and refinement instruments.

An intent reference links the Run to its caller's frozen judgment contract. It
does not grant authority: registration is re-derived from the actual BuildStore,
and the executor still owns confinement, broker admission and terminal evidence.
No target/checker/refiner-specific replay or process runner belongs here.
"""

import asyncio
from dataclasses import replace
from pathlib import Path

from agent.episode_contracts import OpaqueId

from ..broker import ScopedModelBroker
from ..http_broker import ScopedHttpBroker
from ..contracts import RunRegistration
from ..store import RunStoreNotFound
from ..records.experiments import (
    artifact_fields,
    execution_attempts,
    put_record,
    read_record,
    read_reference,
    read_run_intent,
)


class ExecutionPending(RuntimeError):
    """A dispatched Run has no terminal evidence; relaunch is not continuation."""


def register_build(
    executor, builds, inputs, launch, runtime_policy, *, execution_scope=None
):
    registration = RunRegistration.from_admitted_build(
        build_request=inputs.build_request,
        build_attempt=inputs.build_attempt,
        build_receipt=inputs.receipt,
        build_manifest=inputs.manifest,
        launch_request=launch,
        runtime_identity=executor.inspect_runtime_identity(
            destination_root=executor.run_store.runtime_sources_root
        ),
        runtime_policy=runtime_policy,
        execution_scope=execution_scope,
    )
    return registration, builds.verify_source_package(inputs.manifest)


class RunExecution:
    """One dispatch receipt and verified audit source, regardless of caller role."""

    def __init__(self, *, artifacts, builds, runs, executor, duet_binding=None, experiment_service=None):
        if executor.run_store is not runs:
            raise ValueError("experiment executor must use the supplied RunStore")
        self.artifacts, self.builds, self.runs, self.executor = (
            artifacts,
            builds,
            runs,
            executor,
        )
        self.duet_binding = duet_binding
        self.experiment_service = experiment_service

    @staticmethod
    def status(artifacts, runs, run_id):
        run_id = OpaqueId(run_id) if isinstance(run_id, str) else run_id
        attempts = execution_attempts(artifacts, None, run_id)
        if not attempts:
            return {
                "run_id": run_id.value, "candidate_verdict": "unmeasured",
                "execution_status": "not_dispatched",
            }
        history = tuple(OpaqueId(row["record"]["registration"]["run_id"]) for row in attempts)
        with runs.terminal_snapshot_scope(history):
            attempts = execution_attempts(artifacts, runs, run_id)
            statuses = [RunExecution._physical_status(artifacts, runs, row) for row in attempts]
        return {
            **statuses[-1],
            "logical_run_id": attempts[0]["record"]["registration"]["run_id"],
            "attempts": [
                {
                    "run_id": status["run_id"],
                    "registration_hash": row["record"]["registration"]["registration_hash"],
                    "execution_ref": {key: row[key] for key in ("artifact_id", "content_hash")},
                    **{key: status[key] for key in ("execution_status", "evidence_ref") if key in status},
                }
                for row, status in zip(attempts, statuses)
            ],
        }

    @staticmethod
    def _physical_status(artifacts, runs, row):
        binding = row["record"]
        registration = RunRegistration.from_record(binding["registration"])
        run_id = registration.run_id
        result = dict(
            run_id=run_id.value, candidate_verdict="unmeasured",
            intent_ref=binding["intent_ref"],
            mode=binding["mode"],
            scope=binding["scope"],
            progress={
                "admitted": False,
                "reason": "Execution is not host-admitted testing progress.",
            },
        )
        if binding["mode"] == "recorded":
            replay = read_record(artifacts, "playback", run_id=run_id.value)
            if replay is not None:
                result["recorded_execution"] = replay["record"]
        try:
            evidence = runs.read_evidence(run_id)
        except RunStoreNotFound:
            return {
                **result,
                "execution_status": "terminal_evidence_unavailable",
                "limitations": [
                    "This status does not establish process liveness or completion."
                ],
            }
        if evidence.registration_hash != registration.registration_hash:
            raise ValueError("terminal evidence belongs to another execution binding")
        from ..continuation import InterruptedRunRef, resumable_run

        resume_from = (
            InterruptedRunRef.from_run(runs, run_id).as_record()
            if resumable_run(runs, run_id)
            else None
        )
        return {
            **result,
            "execution_status": evidence.terminal_status.value,
            "resume_from": resume_from,
            "evidence_ref": {
                "artifact_id": evidence.evidence_id.value,
                "content_hash": evidence.content_hash.value,
            },
            "typed_status": evidence.as_record()["typed_status"],
            "limitations": [
                "Execution alone establishes no requirement verdict; inspect the bound measurement and parent acceptance."
            ],
        }

    def _validate(self, registration, source_package_path, intent_ref):
        """Recheck current authority without publishing or restarting work."""
        from ..continuation import validate_resume_registration

        validate_resume_registration(self.runs, registration)
        inputs = self.builds.inspection_inputs_for_receipt(
            registration.build_receipt_id
        )
        admitted = RunRegistration.from_admitted_build(
            build_request=inputs.build_request,
            build_attempt=inputs.build_attempt,
            build_receipt=inputs.receipt,
            build_manifest=inputs.manifest,
            launch_request=registration.launch_request,
            runtime_identity=registration.runtime_identity,
            runtime_policy=registration.runtime_policy,
            execution_scope=registration.execution_scope,
            resume_from=registration.resume_from,
        )
        if admitted != registration:
            raise ValueError("experiment Run differs from its admitted build")
        package = self.builds.verify_source_package(inputs.manifest)
        if Path(source_package_path).resolve() != package.resolve():
            raise ValueError("experiment source path differs from its verified package")
        duet_id = registration.duet_id.value
        base = replace(registration, resume_from=None)
        if registration.resume_from is not None:
            prior = read_record(
                self.artifacts, "execution", run_id=registration.resume_from.run_id.value,
            )
            if (
                prior is None or prior["duet_id"] != duet_id
                or prior["record"]["intent_ref"] != intent_ref
                or prior["record"]["registration"]
                != self.runs.read_registration(registration.resume_from.run_id).as_record()
            ):
                raise ValueError("continuation requires its predecessor's exact shared execution intent")
            execution_attempts(self.artifacts, self.runs, registration.resume_from.run_id)
        intent = read_run_intent(self.artifacts, intent_ref, registration)
        if registration.resume_from is not None and intent["kind"] not in {
            "experiment.dispatch.v1", "experiment.instrument.v1", "experiment.launch_intent.v1",
        }:
            raise ValueError("continuation needs a shared execution intent with revalidatable model authority")
        mode, context, recording_ref, cursor = "live_fresh", None, None, None
        subject = None
        if intent["kind"] == "experiment.dispatch.v1":
            from .contracts import ExperimentSpec
            from .playback import execution_context, prepare_playback

            request = ExperimentSpec.from_record(intent["record"]["spec"]).as_record()
            from .boundaries import resolve_run_scope

            selected = resolve_run_scope(
                request,
                inputs=inputs,
                builds=self.builds,
                artifacts=self.artifacts,
                runs=self.runs,
            )
            from .subjects import resolve_subject

            subject = resolve_subject(request, inputs=inputs, artifacts=self.artifacts, builds=self.builds, runs=self.runs)
            if intent["duet_id"] != (registration.duet_id.value if subject is None else subject["owner_duet_id"]):
                raise ValueError("experiment intent belongs to another subject owner")
            if selected != registration.execution_scope:
                raise ValueError(
                    "execution scope differs from its exact experimental intent"
                )
            if getattr(selected, "learning_baseline", None) is not None:
                from ..learning_baseline import load_learning_baseline

                load_learning_baseline(
                    self.runs, registration,
                    OpaqueId(selected.target_ref(registration.logical_run_id.value).episode_id),
                )
            if intent["record"]["registration"] != base.as_record():
                raise ValueError("experimental intent binds another Run registration")
            if subject is not None and subject["kind"] == "refinement_job":
                claim = read_record(self.artifacts, "refinement_job", campaign_id=subject["campaign_id"])
                if (
                    claim is None
                    or claim["record"]["experiment_id"] != ExperimentSpec.from_record(request).experiment_id
                    or claim["record"]["starting_state"] != (
                        subject["starting_state"] if registration.resume_from is None
                        else intent["record"]["plan"]["scope"]["starting_state"]
                    )
                    or claim["record"]["registration"] != base.as_record()
                ):
                    raise ValueError("Refinement campaign changed after its exact experimental starting state was frozen.")
            mode, recording_ref = request["mode"], request["recording_ref"]
            if registration.resume_from is not None and mode == "recorded":
                raise ValueError("recorded-response execution cannot yet be continued; its playback position is not restored")
            if mode not in {"live_fresh", "live_saved", "recorded"}:
                raise ValueError("this mode requires another execution route")
            if (
                mode == "recorded"
                and request["scope"]["kind"] != "component"
                and any(
                    node.contract.testing is not None
                    for node in inputs.build_request.frozen_workflow.workflow.episodes
                )
            ):
                raise ValueError(
                    "recorded execution of a testing workflow needs nested experiment-response replay; live nested experiments are not a fallback"
                )
            context = execution_context(
                registration,
                environment_ref=request["environment_ref"],
                launch_ref=request["launch_ref"],
            )
            if mode == "recorded":
                cursor, context = prepare_playback(
                    self.artifacts, self.runs, recording_ref, registration, context
                )
        elif intent["kind"] == "experiment.instrument.v1":
            from .instruments import validate_instrument_intent
            from .playback import execution_context, prepare_playback

            request = validate_instrument_intent(
                self.artifacts, self.builds, self.runs, intent, base
            )
            mode, recording_ref = request["mode"], request["recording_ref"]
            if registration.resume_from is not None and mode == "recorded":
                raise ValueError("recorded-response execution cannot yet be continued; its playback position is not restored")
            context = execution_context(
                registration,
                environment_ref=request["environment_ref"],
                launch_ref=request["launch_ref"],
            )
            if mode == "recorded":
                cursor, context = prepare_playback(
                    self.artifacts, self.runs, recording_ref, registration, context
                )
        elif registration.execution_scope is not None:
            raise ValueError(
                "selected execution requires a verified experiment dispatch"
            )
        elif intent["kind"] == "experiment.launch_intent.v1":
            from .launches import validate_launch_intent

            validate_launch_intent(self.artifacts, base, intent["record"])
        launch_approval_ref = None
        refiner_job = subject is not None and subject["kind"] == "refinement_job"
        if refiner_job:
            from agent.duet_episode_transport import required_slots

            if self.duet_binding is None:
                raise ValueError("Refinement execution needs its owning Duet's host-bound model configuration.")
            # The original experiment pins its first binding. An explicit
            # continuation can use the owning Duet's new selection for future
            # calls; this attempt's execution record below pins that binding.
            reference = self.duet_binding.reference if registration.resume_from is not None else request["launch_ref"]
            self.duet_binding.validate(artifacts=self.artifacts, reference=reference, owner_duet_id=subject["owner_duet_id"], model_types=required_slots(inputs))
        elif mode in {"live_fresh", "live_saved"} and intent["kind"] in {
            "experiment.dispatch.v1", "experiment.instrument.v1", "experiment.launch_intent.v1"
        }:
            from agent.duet_contracts import digest_record
            from agent.episode_launch_host import resolve_approved_launch
            from episode_builder.planner import required_model_types

            required = set()
            for node in inputs.plan.nodes:
                required.update(required_model_types(node.prompt_specs, node.selected_function_bindings))
            if intent["kind"] == "experiment.launch_intent.v1":
                configuration_hash = intent["record"]["configuration_hash"]
            else:
                launch_record = read_reference(
                    self.artifacts, request["launch_ref"], intent["duet_id"]
                )["record"]
                configuration_hash = digest_record(launch_record).value
            _, _, launch_approval_ref = resolve_approved_launch(
                self.artifacts, intent["duet_id"],
                configuration_hash=configuration_hash, model_types=required,
            )
        # Approval revocation is checked for every actual launch, including the
        # target and the separately approved checking workflow. Being named by a
        # testing request is not a substitute for its original human approval.
        for approval in (
            inputs.build_request.authority_approval,
            inputs.build_request.workflow_approval,
        ):
            stored = self.artifacts.get_approval(approval.approval_id.value)
            if (
                stored is None
                or stored.pop("revoked")
                or stored != approval.as_record()
            ):
                raise ValueError(
                    "experiment build approval is missing, changed or revoked"
                )
        record = {
            "schema_version": 1,
            "registration": registration.as_record(),
            "intent_ref": intent_ref,
            "mode": mode,
            "context": context,
            "launch_approval_ref": launch_approval_ref,
            **({"duet_model_binding_ref": self.duet_binding.reference} if refiner_job else {}),
            "recording_ref": recording_ref,
            "scope": registration.execution_scope.as_record()
            if registration.execution_scope is not None
            else {
                "kind": "workflow",
                "entry_local_id": inputs.plan.root_local_id,
                "included_local_ids": sorted(
                    node.local_id for node in inputs.plan.nodes
                ),
                "children": "execute",
            },
        }
        duet = self.artifacts.get_duet(duet_id)
        if (
            duet is None
            or duet["authority_head_approval_id"]
            != registration.authority_head_approval_id.value
        ):
            raise ValueError("Run no longer matches its Duet authority head")
        return inputs, package, cursor, record, duet

    def _admit(self, registration, source_package_path, intent_ref):
        from .recovery import new_execution_lease

        inputs, package, cursor, record, duet = self._validate(
            registration, source_package_path, intent_ref,
        )
        duet_id = registration.duet_id.value
        artifact = artifact_fields(
            "execution", duet_id=duet_id, record=record, run_id=registration.run_id.value,
        )
        artifact_id = artifact["artifact_id"]
        artifacts = [artifact]
        if registration.resume_from is not None:
            artifacts.append(artifact_fields(
                "continuation", duet_id=duet_id,
                predecessor_run_id=registration.resume_from.run_id.value,
                record={
                    "resume_from": registration.resume_from.as_record(),
                    "execution_ref": {key: artifact[key] for key in ("artifact_id", "content_hash")},
                },
            ))
        lease = new_execution_lease()
        created = self.artifacts.put_artifacts_with_events(
            artifacts=tuple(artifacts),
            events=(
                {
                    "event_type": "experiment_execution_dispatched",
                    "provenance": "host_validation",
                    "record": {
                        "execution_id": artifact_id,
                        "run_id": registration.run_id.value,
                        "intent_ref": intent_ref,
                    },
                },
                {
                    "event_type": "run_execution_owned", "provenance": "host_validation",
                    "record": {
                        "run_id": registration.run_id.value,
                        "registration_hash": registration.registration_hash.value,
                        **lease,
                    },
                },
            ),
            idempotency_artifact_ids=tuple(item["artifact_id"] for item in artifacts),
            duet_id=duet_id,
            expected_state=duet["state"],
            expected_authority_head_approval_id=registration.authority_head_approval_id.value,
        )
        return created, inputs, package, cursor, lease

    def _record_playback(self, registration, cursor):
        record = {"run_id": registration.run_id.value, **cursor.report()}
        put_record(
            self.artifacts,
            "playback",
            run_id=registration.run_id.value,
            duet_id=registration.duet_id.value,
            record=record,
        )

    async def execute(
        self,
        *,
        registration,
        source_package_path,
        intent_ref,
        model_broker,
        http_broker,
        refinement_session=None,
    ):
        if refinement_session is not None:
            if (
                refinement_session.store.evidence.duets is not self.artifacts
                or refinement_session.store.evidence.runs is not self.runs
            ):
                raise ValueError(
                    "refinement session differs from this execution intent"
                )
            if refinement_session.contract.ref.as_record() != intent_ref:
                from .refinement_subjects import validate_session_intent

                intent = read_run_intent(self.artifacts, intent_ref, registration)
                validate_session_intent(self.artifacts, intent, refinement_session)
            await asyncio.to_thread(
                refinement_session.validate_registration, registration
            )
        if any(
            isinstance(broker, (ScopedModelBroker, ScopedHttpBroker))
            and broker.recording is not None
            for broker in (model_broker, http_broker)
        ):
            raise ValueError(
                "recorded brokers must be constructed from the frozen experiment mode, not supplied by its caller"
            )
        from .recovery import claim_execution_owner, release_execution_owner
        from ..host_tasks import commit_local, join_local

        admission = asyncio.create_task(asyncio.to_thread(
            self._admit, registration, source_package_path, intent_ref
        ))
        try:
            created, inputs, package, cursor, lease = await asyncio.shield(admission)
        except asyncio.CancelledError:
            admitted = await join_local(admission, propagate_cancel=False)
            if admitted[0]:
                await commit_local(release_execution_owner, self.artifacts, registration, admitted[-1])
            raise
        if not created:
            try:
                return await asyncio.to_thread(
                    self.runs.read_evidence, registration.run_id
                )
            except RunStoreNotFound as exc:
                try:
                    await asyncio.to_thread(self.runs.read_claim, registration.run_id)
                except RunStoreNotFound:
                    pass
                else:
                    raise ExecutionPending(
                        f"Run {registration.run_id.value} already claimed without terminal "
                        "evidence; inspect or continue that Run, do not relaunch it."
                    ) from exc
        if not created:
            acquisition = asyncio.create_task(asyncio.to_thread(claim_execution_owner, self.artifacts, registration))
            try:
                lease = await asyncio.shield(acquisition)
            except asyncio.CancelledError:
                lease = await join_local(acquisition, propagate_cancel=False)
                await commit_local(release_execution_owner, self.artifacts, registration, lease)
                raise
        try:
            return await self._execute_owned(
                registration=registration, inputs=inputs, package=package, cursor=cursor,
                intent_ref=intent_ref, model_broker=model_broker, http_broker=http_broker,
                refinement_session=refinement_session,
            )
        finally:
            await commit_local(release_execution_owner, self.artifacts, registration, lease)

    async def _execute_owned(
        self, *, registration, inputs, package, cursor, intent_ref,
        model_broker, http_broker, refinement_session,
    ):
        plan = inputs.plan
        experiment_session = None
        if any(
            node.contract.testing is not None
            for node in inputs.build_request.frozen_workflow.workflow.episodes
        ):
            from .session import ExperimentSession
            from .service import ExperimentService

            experiment_session = ExperimentSession(
                service=self.experiment_service or ExperimentService(
                    artifacts=self.artifacts,
                    builds=self.builds,
                    runs=self.runs,
                    executor=self.executor,
                    http_credentials={}
                    if http_broker is None
                    else http_broker.credentials,
                ),
                registration=registration,
                inputs=inputs,
            )
        if cursor is not None:
            model_broker = ScopedModelBroker.from_plan(None, plan, recording=cursor)
            http_broker = ScopedHttpBroker(
                policy=registration.egress_policy,
                credentials={},
                transport=None,
                max_frame_bytes=registration.runtime_policy.max_frame_bytes,
                recording=cursor,
            )
        elif isinstance(model_broker, ScopedModelBroker):
            # A checker has its own approved call graph. Do not accidentally use
            # the target's static path map for its model requests or recursion.
            model_broker = ScopedModelBroker.from_plan(model_broker.transport, plan)
        from .playback import ReplayDivergence

        async def continuation_admission():
            _, _, _, current, _ = await asyncio.to_thread(
                self._validate, registration, package, intent_ref,
            )
            return {
                "registration_hash": registration.registration_hash.value,
                "logical_registration_hash": registration.logical_registration_hash.value,
                "intent_ref": intent_ref,
                "authority_head_approval_id": registration.authority_head_approval_id.value,
                "workflow_approval_id": registration.workflow_approval_id.value,
                **{
                    key: current[key] for key in ("launch_approval_ref", "duet_model_binding_ref")
                    if key in current
                },
            }

        try:
            return await self.executor.execute(
                registration=registration,
                source_package_path=package,
                model_broker=model_broker,
                http_broker=http_broker,
                **({"continuation_admission": continuation_admission} if registration.resume_from is not None else {}),
                **(
                    {"refinement_session": refinement_session}
                    if refinement_session is not None
                    else {}
                ),
                **(
                    {"experiment_session": experiment_session}
                    if experiment_session is not None
                    else {}
                ),
            )
        except ReplayDivergence:
            # The real executor has finalized a claimed Run as invalid. Preserve
            # that terminal evidence and return its explicit divergence report.
            return await asyncio.to_thread(self.runs.read_evidence, registration.run_id)
        finally:
            if cursor is not None:
                await asyncio.to_thread(self._record_playback, registration, cursor)
