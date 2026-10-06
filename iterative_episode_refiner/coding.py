"""Implementer coding turns at the existing host model boundary.

The returned response is still an unadmitted change proposal. Ordinary model
response journaling, proposal admission, measurements and Episode control apply.
Native coding context is recoverable working state, never another Run journal.
"""

import asyncio
import json
import threading
import time
import uuid
from dataclasses import asdict

from agent.duet_contracts import digest_record
from agent.episode_launch_transport import provider_failure
from agent.refinement_coding import CODING_INSTRUCTIONS, coding_backend
from episode_runtime.host_tasks import join_local
from episode_runtime.protocol import episode_id_for_path
from function_library.models import _thaw_json
from llm_call_library.transport import ModelCallFailed, ModelTransportResponse

from .coding_workspace import CodingWorkspace


class RefinementCodingTransport:
    def __init__(self, *, session, binding, transport, record_attempt):
        self.session, self.binding = session, binding
        self.transport, self.record_attempt = transport, record_attempt

    async def __call__(self, request):
        if request.episode_local_id != self.session.nodes["implementer"].local_id:
            return await self.transport(request)
        prompt = json.loads(request.messages[-1]["content"])
        if prompt.get("task") != "change":
            return await self.transport(request)
        diagnostics = await self._prepare_diagnostics(request)
        cancel = threading.Event()
        active = []
        task = asyncio.create_task(asyncio.to_thread(self._run, request, prompt, cancel, active, diagnostics))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            if active:
                active[0].request_interrupt()
            # The existing session closes its process tree before this local
            # operation joins. A cancelled Run cannot leave a writer behind.
            try:
                await join_local(task, propagate_cancel=False)
            finally:
                raise asyncio.CancelledError from None

    def _diagnostic_sources(self, request):
        from .candidate_source import project_candidate_sources
        from .measures import evaluation_bindings

        call, _, _ = self._assignment(request)
        with self.session.view() as view:
            candidate = view.candidate
            bindings = evaluation_bindings(view, self.session.policy, call.assignment)
        writable = set(call.assignment.body["writable_paths"])
        projections = {}
        for binding in (None, *(row for row in bindings if row["purpose"] == "local")):
            projection = project_candidate_sources(
                self.session.store.evidence, self.session.contract, candidate, binding,
            )
            if not writable.intersection(projection.scope.paths.values()):
                continue
            projections[projection.scope.workflow_ref["artifact_id"]] = projection
        return call, candidate, projections.values()

    async def _prepare_diagnostics(self, request):
        from .candidate_environment import prepare_candidate

        await self.session.evaluations.prepare_context(self.session)
        call, candidate, projections = await asyncio.to_thread(self._diagnostic_sources, request)
        diagnostics = []
        for projection in projections:
            preparation = await prepare_candidate(
                self.session.evaluations, self.session, call, candidate, projection,
            )
            if preparation is not None:
                result = preparation["result"]
                execution = result.get("diagnostic_execution") or self.session.evaluations.environment_context()["coding_diagnostics"]
                diagnostics.append({
                    "source_paths": sorted(projection.scope.paths.values()),
                    "status": result["status"], "diagnostics": result["diagnostics"],
                    "python_executable": result["python_executable"],
                    "site_packages": result["site_packages"] if execution["direct_interpreter_available"] else None,
                    "execution": execution,
                    "preparation_ref": result["preparation_ref"], "log_refs": result["log_refs"],
                    "meaning": execution["guidance"],
                })
        return diagnostics

    def _assignment(self, request):
        if request.model_type not in self.binding.record["model_types"]:
            raise ValueError("Coding request names a slot outside the frozen Duet binding")
        path = [{"grain": grain, "key": key} for grain, key in request.episode_path]
        call = self.session._caller(episode_id_for_path(self.session.registration.logical_run_id, path), path)
        if call.assignment.body["role"] != "implementer" or call.unit_id is None:
            raise ValueError("Coding requires an active host-admitted Implementer unit")
        with self.session.view() as view:
            if view.entry("invocation", call.invocation_id.value).status != "active":
                raise ValueError("Coding invocation is not active")
            candidate = view.candidate.ref
        return call, candidate, self.session.snapshot(call)["context"]

    def _latest(self, kind, invocation_id):
        # Use the shared artifact store. Neither native transcript discovery nor
        # a filesystem sentinel can claim an admitted thread/workspace binding.
        with self.session.view() as view:
            row = view.connection.execute(
                "SELECT record_json FROM artifacts WHERE duet_id = ? AND kind = ? "
                "AND json_extract(record_json, '$.invocation_id') = ? ORDER BY rowid DESC LIMIT 1",
                (self.session.duet_id, f"refinement.{kind}.v1", invocation_id),
            ).fetchone()
        return None if row is None else json.loads(row[0])

    def _prepare(self, call, candidate, context, prompt, instructions, runtime_id):
        from openchia_cli.active_sessions import _pid_liveness

        saved = self._latest("coding_thread", call.invocation_id.value)
        if saved is not None:
            owner = saved["process"]
            if _pid_liveness(owner["pid"], owner["process_start_time"]) is not False:
                raise ValueError("Previous coding agent is live or unverifiable; its workspace cannot be resumed")
        scope = call.assignment.body
        builds = self.session.store.evidence.builds
        root = builds.root / "refinement_coding" / self.session.campaign_id.value / call.invocation_id.value
        workspace = CodingWorkspace(
            root / call.unit_id.value,
            source_files=context["inputs"].get("source_files", {}),
            writable_paths=scope["writable_paths"], protected_paths=scope["protected_paths"],
        )
        identity = {
            "invocation_id": call.invocation_id.value, "unit_id": call.unit_id.value,
            "candidate_ref": candidate.as_record(), "workspace": str(workspace.root),
            "assignment_ref": call.assignment.ref.as_record(),
        }
        previous = self._latest("coding_workspace", call.invocation_id.value)
        assignment_context = _thaw_json({
            "host_context": context, "episode_request": prompt,
            "workspace": {"write_paths": sorted(workspace.writable_paths)},
        })
        if previous != identity:
            workspace.stage(assignment_context)
            self.session.put_data("coding_workspace", identity)
        elif not workspace.root.is_dir():
            raise ValueError("Saved coding workspace is missing; cannot silently discard unfinished edits")
        else:
            workspace.refresh_context(assignment_context)
        # A model/instruction change opens a new native context instead of
        # silently mutating an existing conversation's cached prefix.
        context_id = digest_record({"binding": self.binding.reference, "instructions": instructions,
                                    "coding_runtime": runtime_id}).value
        resume = saved["thread_id"] if saved and saved["context_id"] == context_id else None
        return workspace, root / "sessions" / context_id, resume, context_id, identity

    def _run(self, request, prompt, cancel, active, diagnostics):
        call, candidate, context = self._assignment(request)
        context = _thaw_json(context)
        context["inputs"]["target_environment"]["coding_diagnostics"] = diagnostics
        backend = coding_backend(self.binding)
        instructions = request.messages[0]["content"] + "\n\n" + CODING_INSTRUCTIONS
        workspace, native_home, resume, context_id, identity = self._prepare(
            call, candidate, context, prompt, instructions, backend.runtime_id,
        )
        route = self.binding.record["route"]
        receipt = {
            **identity, "binding_ref": self.binding.reference,
            "owner_duet_id": self.binding.owner_duet_id,
            "session_id": self.binding.record["session_id"],
            "run_id": self.session.registration.run_id.value,
            "call_id": uuid.uuid4().hex, "task": request.task,
            "model_type": request.model_type, "episode_local_id": request.episode_local_id,
            "coding_runtime": backend.runtime_id,
            **{key: route[key] for key in ("model", "provider", "base_url", "api_mode")},
        }
        started = time.monotonic()
        self.record_attempt({**receipt, "state": "started"})
        audit_errors = []
        provider_errors = []

        def observe(note):
            kind = note["kind"]
            try:
                reference = self.session.put_data("coding_activity", {**receipt, "notification": note})
                self.record_attempt({**receipt, "state": "activity", "activity": kind,
                                     "evidence_ref": reference.as_record()})
                if kind == "api_error":
                    provider_errors.append(note.get("error"))
                    active[0].request_interrupt()
            except Exception as exc:
                # Session.on_event is a display hook and swallows exceptions.
                # An audit failure must instead interrupt and prevent publication.
                audit_errors.append(exc)
                active[0].request_interrupt()

        coder = None
        try:
            if cancel.is_set():
                raise asyncio.CancelledError
            coder = backend(
                binding=self.binding, workspace=workspace.root, state_dir=native_home,
                instructions=instructions, resume_thread_id=resume, on_event=observe,
            )
            active.append(coder)
            thread_id = coder.ensure_started()
            self.session.put_data("coding_thread", {
                "invocation_id": call.invocation_id.value, "context_id": context_id,
                "thread_id": thread_id, "binding_ref": self.binding.reference,
                "coding_runtime": backend.runtime_id,
                "process": coder.process_identity(),
            })
            if cancel.is_set():
                raise asyncio.CancelledError
            result = coder.run_turn(
                "Work on the current assignment in .openchia-assignment.json in "
                f"{workspace.root}. This is unit {call.unit_id.value}. "
                "Existing edits in this workspace may be unfinished work from an interrupted "
                "attempt; inspect them. The host candidate and measured feedback in the "
                "assignment are authoritative. Produce the next scoped candidate revision.",
                turn_timeout=None,
            )
            turn_ref = self.session.put_data("coding_turn", {**receipt, "result": asdict(result)})
            if audit_errors:
                raise RuntimeError("Coding activity could not be durably recorded") from audit_errors[0]
            if cancel.is_set():
                raise asyncio.CancelledError
            if provider_errors:
                raise RuntimeError(f"Coding provider error: {json.dumps(provider_errors[-1])}")
            if result.error or result.interrupted:
                raise RuntimeError(result.error or "Coding agent turn was interrupted")
            # Stop all tool descendants before reading the actual candidate.
            coder.close()
            with self.session.view() as view:
                if view.candidate.ref != candidate:
                    raise ValueError("Candidate changed while its coding turn was running")
            try:
                proposal = workspace.capture()
            except (ValueError, OSError) as exc:
                # This is a bad proposed edit, not an API failure. Ordinary
                # proposal admission returns its rejection as next-unit feedback.
                proposal = {"invalid_workspace_change": str(exc)}
            self.record_attempt({**receipt, "state": "succeeded", "turn_ref": turn_ref.as_record(),
                                 "elapsed_seconds": time.monotonic() - started})
            return ModelTransportResponse(text=json.dumps(proposal), route={
                **receipt, "coding_turn_ref": turn_ref.artifact_id.value,
                "coding_turn_hash": turn_ref.content_hash.value,
                "response_model": route["model"],
            })
        except asyncio.CancelledError:
            self.record_attempt({**receipt, "state": "cancelled", "elapsed_seconds": time.monotonic() - started})
            raise
        except Exception as exc:
            details = provider_failure(exc, route, credential=self.binding.api_key, request=request)
            self.record_attempt({**receipt, **details, "state": "failed", "elapsed_seconds": time.monotonic() - started})
            raise ModelCallFailed("Implementer coding-agent call failed; its owning Run must stop.", receipt) from None
        finally:
            if coder is not None:
                coder.close()
