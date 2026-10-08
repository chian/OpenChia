"""The normal build's automatic handoff into the existing refinement system."""

import asyncio

from agent.duet_episode_transport import DuetEpisodeBinding
from episode_builder.reference import EpisodeReferenceResolver
from episode_builder.service import EpisodeBuilder
from episode_runtime.contracts import RuntimePolicy
from episode_runtime.records.experiments import put_data, put_record, read_record
from episode_runtime.testing_harness.execution import register_build
from episode_runtime.testing_harness.inputs import workflow_template
from episode_runtime.testing_harness.service import ExperimentService
from iterative_episode_refiner.build_entry import build_experiment, prepare_build
from iterative_episode_refiner.campaign_store import CampaignStore
from iterative_episode_refiner.evaluation import RefinementEvaluations
from iterative_episode_refiner.evidence import EvidenceReader
from iterative_episode_refiner.program import RefinerEmitter, RefinerPlanner
from llm_call_library import CallOptions

from .build_refinement_authority import authorize_program


class BuildRefinement:
    def __init__(self, host, *, binding=None):
        self.host = host
        # Check both routes before starting work, never half way through a job.
        self.executor = host._runtime_executor()
        self.binding = binding or DuetEpisodeBinding.from_bound_agent(
            artifacts=host.store,
            owner_duet_id=host.identity.duet_id.value,
            agent=host._duet_agent,
            model_types={"refinement"},
        )

    async def continue_job(self, job, target_builder, launch):
        from episode_runtime.records.experiments import read_reference

        host = self.host
        target_launch = await asyncio.to_thread(
            put_data, host.store, host.identity.duet_id.value, "launch", launch.record
        )
        service = ExperimentService(
            artifacts=host.store, builds=host.build_store, runs=host.run_store,
            executor=self.executor, http_credentials=host.egress_credentials,
            duet_binding=self.binding,
            refinement_evaluations=RefinementEvaluations(
                builder=target_builder, executor=self.executor,
                target_launch_ref=target_launch, http_credentials=host.egress_credentials,
                progress_callback=self.progress,
            ),
        )
        try:
            status = await asyncio.to_thread(service.status, host.store, host.run_store, job["experiment_id"])
            if "refinement" not in status or status["execution_status"] in {"interrupted", "cancelled", "resource_limited", "terminal_evidence_unavailable", "failed"}:
                status = await service.continue_interrupted(experiment_id=job["experiment_id"])
        except asyncio.CancelledError:
            status = await asyncio.to_thread(
                service.status, host.store, host.run_store, job["experiment_id"]
            )
            if "refinement" not in status:
                raise
        if "refinement" not in status:
            raise ValueError(f"continued refinement has no committed result: {status}")
        row = await asyncio.to_thread(
            read_reference, host.store, status["refinement"]["result_ref"], host.identity.duet_id.value
        )
        return row["record"]

    def progress(self, stage):
        with self.host._build_lock:
            if self.host._build_state != "cancel_requested":
                self.host._build_state = stage
                self.host._build_progress["stage"] = stage

    async def run(self, target_request, target_inputs, target_handoff, target_builder, launch):
        host = self.host
        request = await asyncio.to_thread(authorize_program, host, target_request)
        options = CallOptions(model_type="refinement")
        resolver = EpisodeReferenceResolver()
        program = EpisodeBuilder(
            store=host.build_store,
            planning_options=options,
            emission_options=options,
            reference_resolver=resolver,
            planner=RefinerPlanner(
                reference_resolver=resolver,
                call_options=options,
                model_slot_catalog={"refinement": self.binding.record["route"]},
            ),
            emitter=RefinerEmitter(call_options=options),
            model_slot_catalog={"refinement": self.binding.record["route"]},
        )
        from .openchia_build_recovery import continued_materialization_request

        request, receipt = await asyncio.to_thread(
            continued_materialization_request, host, request, program
        )
        if receipt is None:
            receipt = await program.build(request)
        if not receipt.materialized:
            raise ValueError(
                f"shipped refiner failed ordinary source admission: {[d.as_record() for d in receipt.deficits]}"
            )
        inputs = await asyncio.to_thread(
            host.build_store.inspection_inputs_for_receipt, receipt.receipt_id
        )
        registration, _package = await asyncio.to_thread(
            register_build,
            self.executor,
            host.build_store,
            inputs,
            workflow_template(request.frozen_workflow),
            RuntimePolicy(),
        )
        campaigns = CampaignStore(
            host.store, EvidenceReader(host.store, host.build_store, host.run_store)
        )
        prepared = await asyncio.to_thread(
            prepare_build,
            host,
            campaigns,
            target_inputs,
            target_handoff,
            registration,
            registration.runtime_identity,
            launch.model_slot_catalog(),
        )
        target_launch = await asyncio.to_thread(
            put_data, host.store, host.identity.duet_id.value, "launch", launch.record
        )
        evaluations = RefinementEvaluations(
            builder=target_builder,
            executor=self.executor,
            target_launch_ref=target_launch,
            http_credentials=host.egress_credentials,
            progress_callback=self.progress,
        )
        service = ExperimentService(
            artifacts=host.store,
            builds=host.build_store,
            runs=host.run_store,
            executor=self.executor,
            http_credentials=host.egress_credentials,
            duet_binding=self.binding,
            refinement_evaluations=evaluations,
        )
        spec = await asyncio.to_thread(
            build_experiment,
            host,
            prepared,
            inputs,
            self.binding,
            registration.runtime_identity,
        )
        await asyncio.to_thread(
            put_record,
            host.store,
            "build_job",
            duet_id=host.identity.duet_id.value,
            build_request_id=target_request.build_request_id.value,
            record={
                "construction_start": {
                    "build_request_id": target_inputs.build_request.build_request_id.value,
                    "build_attempt_id": target_inputs.build_attempt.build_attempt_id.value,
                },
                "campaign_ref": prepared.contract.ref.as_record(),
                "experiment_id": spec.experiment_id,
                "experiment": spec.as_record(),
            },
        )
        try:
            result = await service.run(spec)
        except asyncio.CancelledError:
            row = await asyncio.to_thread(
                read_record,
                host.store,
                "refinement_result",
                experiment_id=spec.experiment_id,
            )
            if row is None:
                raise
            return row["record"]
        row = await asyncio.to_thread(
            read_record,
            host.store,
            "refinement_result",
            experiment_id=spec.experiment_id,
        )
        if row is None:
            raise ValueError(f"refinement did not publish its final result: {result}")
        return row["record"]
