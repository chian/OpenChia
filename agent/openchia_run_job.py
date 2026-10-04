"""Ordinary Duet Run lifecycle using the shared confined execution service."""

import asyncio
import threading
from typing import Any, Optional

from agent.duet_contracts import DuetProvenance
from agent.openchia_host import OpenChiaHostError, _describe_exception
from episode_runtime import (
    HttpxHostTransport, RunEvidence, RunRegistration, RuntimePolicy,
    ScopedHttpBroker, ScopedModelBroker,
)


def start_run(host) -> dict[str, Any]:
    """Start one fresh, explicitly requested Run of the current build."""

    with host._build_lock:
        if host._build_thread is not None and host._build_thread.is_alive():
            raise OpenChiaHostError(
                "an Episode build must finish before an Episode Run"
            )
        with host._run_lock:
            if (
                host._run_thread is not None
                and host._run_thread.is_alive()
            ):
                raise OpenChiaHostError(
                    "an Episode Run is already active"
                )
            (
                baseline,
                request,
                attempt,
                receipt,
                manifest,
                plan,
                source_package,
            ) = host._runnable_build_context()
            launch_request = host._root_launch_request(request, plan)
            from episode_builder.planner import required_model_types
            model_types = set()
            for node in plan.nodes:
                try:
                    model_types.update(required_model_types(node.prompt_specs, node.selected_function_bindings))
                except ValueError as exc:
                    raise OpenChiaHostError(f"Episode {node.local_id}: {exc}") from None
            host._require_approved_launch(model_types=model_types)
            executor = host._runtime_executor()
            runtime_identity = executor.inspect_runtime_identity(
                destination_root=host.run_store.runtime_sources_root,
            )
            registration = RunRegistration.from_admitted_build(
                build_request=request,
                build_attempt=attempt,
                build_receipt=receipt,
                build_manifest=manifest,
                launch_request=launch_request,
                runtime_identity=runtime_identity,
                runtime_policy=RuntimePolicy(),
            )
            launch_id, launch = host._prepare_model_launch("run", registration.run_id.value,
                model_types=model_types)
            broker = ScopedModelBroker(host._model_launch_transport(launch_id, launch),
                episode_paths={host._model_node_path(node.local_id, plan): node.local_id for node in plan.nodes})
            http_broker = ScopedHttpBroker(
                policy=registration.egress_policy,
                credentials=host.egress_credentials,
                transport=HttpxHostTransport(),
                max_frame_bytes=registration.runtime_policy.max_frame_bytes,
            )
            from episode_runtime.testing.execution import RunExecution
            from episode_runtime.testing.launches import record_launch_intent

            execution = RunExecution(
                artifacts=host.store, builds=host.build_store,
                runs=host.run_store, executor=executor,
            )
            intent_ref = record_launch_intent(
                host.store, registration, launch_id, launch.configuration_hash,
            )
            host._run_registration = registration
            host._run_evidence = None
            host._run_baseline = None
            host._run_error = None
            host._run_cancel_requested = False
            host._run_loop = None
            host._run_task = None
            host._run_state = "starting"

            def run_worker() -> None:
                loop = asyncio.new_event_loop()
                task = loop.create_task(
                    execution.execute(
                        registration=registration,
                        source_package_path=source_package,
                        intent_ref=intent_ref,
                        model_broker=broker,
                        http_broker=http_broker,
                    )
                )
                with host._run_lock:
                    host._run_loop = loop
                    host._run_task = task
                    if host._run_cancel_requested:
                        task.cancel()
                    else:
                        host._run_state = "running"
                evidence: Optional[RunEvidence] = None
                error: Optional[str] = None
                try:
                    evidence = loop.run_until_complete(task)
                except asyncio.CancelledError:
                    try:
                        evidence = host._read_terminal_evidence(
                            registration
                        )
                    except Exception as exc:
                        error = _describe_exception(exc)
                except BaseException as exc:
                    error = _describe_exception(exc)
                    try:
                        evidence = host._read_terminal_evidence(
                            registration
                        )
                    except Exception as evidence_exc:
                        error = (
                            f"{error}; evidence: "
                            f"{type(evidence_exc).__name__}: {evidence_exc}"
                        )
                try:
                    if evidence is not None:
                        durable_evidence = host.run_store.read_evidence(
                            registration.run_id
                        )
                        if (
                            durable_evidence.as_record()
                            != evidence.as_record()
                        ):
                            raise OpenChiaHostError(
                                "executor result differs from durable Run evidence"
                            )
                        evidence = durable_evidence
                        with host._run_lock:
                            host._run_evidence = evidence
                        recorded_baseline = host._persist_run_evidence(
                            registration=registration,
                            baseline=baseline,
                            evidence=evidence,
                        )
                        with host._run_lock:
                            host._run_baseline = recorded_baseline
                            host._run_state = (
                                evidence.terminal_status.value
                            )
                            host._run_error = error
                        host.store.append_event(
                            duet_id=host.identity.duet_id.value,
                            event_type="run_finished",
                            provenance=(
                                DuetProvenance.HOST_VALIDATION.value
                            ),
                            record={
                                "run_id": registration.run_id.value,
                                "registration_hash": (
                                    registration.registration_hash.value
                                ),
                                "evidence_id": evidence.evidence_id.value,
                                "evidence_hash": evidence.content_hash.value,
                                "audit_log_id": (
                                    evidence.audit_log_id.value
                                ),
                                "audit_log_hash": (
                                    evidence.audit_log_hash.value
                                ),
                                "terminal_status": (
                                    evidence.terminal_status.value
                                ),
                                "refinement_baseline_id": (
                                    recorded_baseline.baseline_id.value
                                ),
                            },
                        )
                    else:
                        with host._run_lock:
                            cancelled = host._run_cancel_requested
                            host._run_state = (
                                "cancelled_before_claim"
                                if cancelled
                                else "host_error"
                            )
                            host._run_error = error
                        host.store.append_event(
                            duet_id=host.identity.duet_id.value,
                            event_type=(
                                "run_cancelled_before_claim"
                                if cancelled
                                else "run_host_failure"
                            ),
                            provenance=(
                                DuetProvenance.HOST_VALIDATION.value
                            ),
                            record={
                                "run_id": registration.run_id.value,
                                "registration_hash": (
                                    registration.registration_hash.value
                                ),
                                "error": error,
                            },
                        )
                except Exception as exc:
                    with host._run_lock:
                        host._run_state = "host_error"
                        host._run_error = (
                            f"{type(exc).__name__}: {exc}"
                        )
                finally:
                    if not task.done():
                        task.cancel()
                        try:
                            loop.run_until_complete(task)
                        except BaseException:
                            pass
                    loop.close()
                    with host._run_lock:
                        host._run_loop = None
                        host._run_task = None
                        host._run_thread = None

            worker = threading.Thread(
                target=run_worker,
                name=f"openchia-run-{registration.run_id.value[-12:]}",
                daemon=False,
            )
            host._run_thread = worker
            host.store.append_event(
                duet_id=host.identity.duet_id.value,
                event_type="run_requested",
                provenance=DuetProvenance.HUMAN_INPUT.value,
                record={
                    "intent_ref": intent_ref,
                    "run_id": registration.run_id.value,
                    "registration_hash": (
                        registration.registration_hash.value
                    ),
                    "build_request_id": (
                        registration.build_request_id.value
                    ),
                    "build_attempt_id": (
                        registration.build_attempt_id.value
                    ),
                    "build_receipt_id": (
                        registration.build_receipt_id.value
                    ),
                    "manifest_id": registration.manifest_id.value,
                },
            )
            try:
                worker.start()
            except Exception:
                host._run_thread = None
                host._run_state = "host_error"
                raise
    return host.run_status()
