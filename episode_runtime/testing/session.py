"""Scoped worker access to the shared service, not another experiment runner."""

import asyncio

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json
from function_library.testing_contract import validate_operation_payload

from ..broker import admitted_call_graph, resolve_call_path
from ..contracts import RunEventKind
from ..protocol import episode_id_for_path
from .contracts import ExperimentSpec
from ..records.experiments import put_record, read_record, read_reference


class ExperimentAccessError(RuntimeError):
    """A worker attempted to exceed its approved testing access."""


class ExperimentSession:
    def __init__(self, *, service, registration, inputs):
        self.service, self.registration = service, registration
        if (
            inputs.receipt.receipt_id != registration.build_receipt_id
            or inputs.build_request.frozen_workflow.workflow_hash
            != registration.workflow_hash
        ):
            raise ValueError("testing session belongs to another admitted build")
        self.paths, self.edges = admitted_call_graph(inputs.plan)
        self.contracts = {
            node.local_id: node.contract.testing
            for node in inputs.build_request.frozen_workflow.workflow.episodes
            if node.contract.testing is not None
        }
        if not self.contracts:
            raise ValueError("workflow has no approved testing access")

    def validate_registration(self, registration):
        if registration != self.registration:
            raise ValueError("testing session belongs to another registered Run")

    def _caller(self, episode_id, path):
        if episode_id_for_path(self.registration.logical_run_id, path).value != episode_id:
            raise ExperimentAccessError("testing caller differs from its runtime path")
        if path[0]["key"] != self.registration.logical_run_id.value:
            raise ExperimentAccessError("testing caller names another root invocation")
        local_id = resolve_call_path(
            self.paths, self.edges, tuple(row["grain"] for row in path)
        )
        contract = self.contracts.get(local_id)
        if contract is None:
            raise ExperimentAccessError(
                "this Episode has no human-approved testing contract"
            )
        events = self.service.runs.read_execution_prefix(self.registration.run_id)
        lifecycle = [
            event
            for event in events
            if event.episode_id == OpaqueId(episode_id)
            and event.kind
            in {RunEventKind.EPISODE_STARTED, RunEventKind.EPISODE_COMPLETED}
        ]
        if (
            not lifecycle
            or lifecycle[-1].kind is not RunEventKind.EPISODE_STARTED
            or canonical_json(lifecycle[-1].payload["episode_path"])
            != canonical_json(path)
        ):
            raise ExperimentAccessError(
                "testing caller has no active recorded invocation"
            )
        return contract.as_record()

    def _read_owned(self, episode_id, experiment_id):
        row = read_record(
            self.service.artifacts,
            "access",
            run_id=self.registration.logical_run_id.value,
            episode_id=episode_id,
            key=experiment_id,
        )
        if row is None:
            raise ExperimentAccessError("experiment is not assigned to this invocation")
        row = read_reference(
            self.service.artifacts,
            {
                "artifact_id": row["artifact_id"],
                "content_hash": row["content_hash"],
            },
            self.registration.duet_id.value,
        )
        record = row["record"]
        spec = ExperimentSpec.from_record(record["spec"])
        if (
            row["kind"] != "experiment.access.v1"
            or record["registration_hash"] != self.registration.logical_registration_hash.value
            or record["episode_id"] != episode_id
            or spec.experiment_id != experiment_id
        ):
            raise ExperimentAccessError(
                "experiment access receipt differs from its owner"
            )
        return record

    def _recording_allowed(self, caller, target, reference):
        if reference in target["recording_refs"]:
            return True
        row = read_record(
            self.service.artifacts,
            "recording_access",
            run_id=self.registration.logical_run_id.value,
            episode_id=caller,
            key=reference,
        )
        if row is None:
            return False
        owned = self._read_owned(caller, row["record"]["experiment_id"])
        return (
            row["kind"] == "experiment.recording_access.v1"
            and row["duet_id"] == self.registration.duet_id.value
            and row["record"]["recording_ref"] == reference
            and owned["spec"]["build_receipt_ref"] == target["build_receipt_ref"]
        )

    def _authorize(self, contract, caller, spec):
        value = spec.as_record()
        if (
            value["scope"]["kind"] not in contract["scope_kinds"]
            or value["mode"] not in contract["modes"]
        ):
            raise ExperimentAccessError(
                "scope or mode is outside approved testing access"
            )
        targets = [
            target
            for target in contract["targets"].values()
            if all(
                target[key] == value[key]
                for key in (
                    "candidate_ref",
                    "build_receipt_ref",
                    "environment_ref",
                    "campaign_ref",
                )
            )
        ]
        requested = [
            {key: row[key] for key in ("requirement_ref", "measure_ref")}
            for row in value["requirements"]
        ]
        for target in targets:
            if not all(row in target["requirements"] for row in requested):
                continue
            if value["launch_ref"] != target["launch_ref"] and not (
                value["launch_ref"] is None
                and value["mode"] in {"recorded", "numerical"}
            ):
                continue
            context = value["boundary"]["parent_context_ref"]
            if (
                context is not None
                and context not in target["parent_context_refs"]
                and not self._boundary_allowed(caller, context)
            ):
                continue
            references = [value["recording_ref"], value["start"]["artifact_ref"]]
            if all(
                ref is None or self._recording_allowed(caller, target, ref)
                for ref in references
            ):
                return target
        raise ExperimentAccessError(
            "candidate, criteria, inputs or context exceed the assigned targets"
        )

    def _remember(self, caller, spec):
        record = {
            "registration_hash": self.registration.logical_registration_hash.value,
            "episode_id": caller,
            "spec": spec.as_record(),
        }
        put_record(
            self.service.artifacts,
            "access",
            run_id=self.registration.logical_run_id.value,
            episode_id=caller,
            key=spec.experiment_id,
            duet_id=self.registration.duet_id.value,
            record=record,
        )

    async def exchange(self, *, episode_id, episode_path, operation, payload):
        caller = episode_id.value if isinstance(episode_id, OpaqueId) else episode_id
        contract = await asyncio.to_thread(
            self._caller, caller, _thaw_json(episode_path)
        )
        handler = {
            "describe": self._describe,
            "history": self._history,
            "inventory": self._inventory,
            "preview": self._preview,
            "run": self._run,
            "continue": self._continue,
            "status": self._status,
            "results": self._status,
            "compare": self._compare,
            "recording": self._recording,
            "boundary": self._boundary,
        }.get(operation)
        if handler is None:
            raise ExperimentAccessError("unknown testing operation")
        try:
            validate_operation_payload(operation, payload)
            return await handler(contract, caller, _thaw_json(payload))
        except ValueError as exc:
            # An invalid experimental design is feedback, not permission to
            # invent a broader experiment or substitute a live execution.
            return {
                "operation_status": "rejected",
                "reason": str(exc),
                "progress": {"admitted": False},
            }

    async def _describe(self, contract, caller, payload):
        from .schema import vocabulary

        return {
            **vocabulary(),
            "assigned_access": contract,
            "limitations": [
                "A pass covers only the selected requirements; parent acceptance and progress remain separate."
            ],
        }

    async def _history(self, contract, caller, payload):
        return await asyncio.to_thread(
            self._history_records, contract, caller, payload["query"]
        )

    async def _inventory(self, contract, caller, payload):
        return await asyncio.to_thread(
            self._inventory_records, contract, caller, payload
        )

    def _inventory_records(self, contract, caller, payload):
        from ..records.catalog import experiment_record_owner
        from ..records.inventory import InventoryRequest

        request = InventoryRequest.model_validate(payload)
        source = request.source.model_dump(mode="json")
        if request.source.kind == "experiment":
            owned = self._read_owned(caller, request.source.experiment_id)
            owner = experiment_record_owner(self.service.artifacts, owned["spec"])
            if owner is None:
                raise ExperimentAccessError(
                    "assigned experiment has no committed execution or numerical recording"
                )
        elif request.source.kind == "recording":
            target = next(
                (
                    target
                    for target in contract["targets"].values()
                    if self._recording_allowed(caller, target, source["recording_ref"])
                ),
                None,
            )
            if target is None:
                raise ExperimentAccessError(
                    "recording inventory is not assigned to this invocation"
                )
            owner = self.service.builds.inspection_inputs_for_receipt(
                target["build_receipt_ref"]["artifact_id"]
            ).build_request.frozen_workflow.duet_id.value
        else:
            raise ExperimentAccessError(
                "worker inventory requires an assigned experiment or exact recording, not an arbitrary Run"
            )
        return self.service.inventory(
            self.service.artifacts,
            self.service.runs,
            duet_id=owner,
            source=source,
            query=request.query.model_dump(mode="json"),
        )

    def _history_records(self, contract, caller, query):
        from ..records.catalog import recording_choice

        result = self.service.history(
            self.service.artifacts,
            self.service.runs,
            duet_id=self.registration.duet_id.value,
            query=query,
            invocation={
                "run_id": self.registration.logical_run_id.value,
                "episode_id": caller,
                "registration_hash": self.registration.logical_registration_hash.value,
            },
        )
        for name, target in contract["targets"].items():
            if not target["recording_refs"]:
                continue
            owner = self.service.builds.inspection_inputs_for_receipt(
                target["build_receipt_ref"]["artifact_id"]
            ).build_request.frozen_workflow.duet_id.value
            result["assigned_recordings"].extend(
                {
                    "target": name,
                    **recording_choice(
                        read_reference(self.service.artifacts, ref, owner),
                        artifacts=self.service.artifacts,
                        runs=self.service.runs,
                    ),
                }
                for ref in target["recording_refs"]
            )
        return result

    async def _preview(self, contract, caller, payload):
        spec = ExperimentSpec.from_record(payload["spec"])
        await asyncio.to_thread(self._authorize, contract, caller, spec)
        return await asyncio.to_thread(
            self.service.preview, spec,
        )

    async def _run(self, contract, caller, payload):
        spec = ExperimentSpec.from_record(payload["spec"])
        await asyncio.to_thread(self._authorize, contract, caller, spec)
        await asyncio.to_thread(self._remember, caller, spec)
        return await self.service.run(spec)

    async def _status(self, contract, caller, payload):
        await asyncio.to_thread(self._read_owned, caller, payload["experiment_id"])
        return await asyncio.to_thread(
            self.service.status,
            self.service.artifacts,
            self.service.runs,
            payload["experiment_id"],
        )

    async def _continue(self, contract, caller, payload):
        owned = await asyncio.to_thread(
            self._read_owned, caller, payload["experiment_id"]
        )
        spec = ExperimentSpec.from_record(owned["spec"])
        await asyncio.to_thread(self._authorize, contract, caller, spec)
        # Ownership of this exact experiment is necessary but not sufficient:
        # the common service verifies the final interruption and current
        # authority before the existing executor can reconstruct the prefix.
        return await self.service.continue_run(
            experiment_id=payload["experiment_id"], resume_from=payload["resume_from"]
        )

    async def _compare(self, contract, caller, payload):
        from .comparison import compare_experiments

        for key in ("before", "after"):
            await asyncio.to_thread(self._read_owned, caller, payload[key])
        return await asyncio.to_thread(
            compare_experiments,
            self.service.artifacts,
            payload["before"],
            payload["after"],
        )

    async def _recording(self, contract, caller, payload):
        return await asyncio.to_thread(
            self._save_recording, caller, payload["experiment_id"]
        )

    def _boundary_allowed(self, caller, reference):
        row = read_record(
            self.service.artifacts,
            "boundary_access",
            run_id=self.registration.logical_run_id.value,
            episode_id=caller,
            key=reference,
        )
        if row is None:
            return False
        self._read_owned(caller, row["record"]["experiment_id"])
        return (
            row["kind"] == "experiment.boundary_access.v1"
            and row["duet_id"] == self.registration.duet_id.value
            and row["record"]["parent_context_ref"] == reference
        )

    async def _boundary(self, contract, caller, payload):
        return await asyncio.to_thread(self._save_boundary, caller, payload)

    def _save_boundary(self, caller, payload):
        from .boundaries import capture_boundary
        from .units import capture_unit_boundary

        self._read_owned(caller, payload["experiment_id"])
        status = self.service.status(
            self.service.artifacts, self.service.runs, payload["experiment_id"]
        )
        if "run_id" not in status:
            raise ValueError("experiment has no recorded Run")
        selector = "unit_id" if "unit_id" in payload else "episode_id"
        capture = capture_unit_boundary if selector == "unit_id" else capture_boundary
        result = capture(
            self.service.artifacts,
            self.service.runs,
            status["run_id"],
            payload[selector],
        )
        # Grant only the returned selector. A unit prefix is not permission to
        # reuse later responses from the containing Run.
        put_record(
            self.service.artifacts,
            "recording_access",
            run_id=self.registration.logical_run_id.value,
            episode_id=caller,
            key=result["recording_ref"],
            duet_id=self.registration.duet_id.value,
            record={
                "experiment_id": payload["experiment_id"],
                "recording_ref": result["recording_ref"],
            },
        )
        record = {
            "experiment_id": payload["experiment_id"],
            "parent_context_ref": result["parent_context_ref"],
        }
        put_record(
            self.service.artifacts,
            "boundary_access",
            run_id=self.registration.logical_run_id.value,
            episode_id=caller,
            key=result["parent_context_ref"],
            duet_id=self.registration.duet_id.value,
            record=record,
        )
        return result

    def _save_recording(self, caller, experiment_id):
        from .recordings import save_recording, load_recording, recording_summary

        owned = self._read_owned(caller, experiment_id)
        status = self.service.status(
            self.service.artifacts, self.service.runs, experiment_id
        )
        if "run_id" not in status:
            raise ValueError("experiment has no recorded Run")
        reference = save_recording(
            self.service.artifacts, self.service.runs, status["run_id"]
        )
        record = {"experiment_id": experiment_id, "recording_ref": reference}
        put_record(
            self.service.artifacts,
            "recording_access",
            run_id=self.registration.logical_run_id.value,
            episode_id=caller,
            key=reference,
            duet_id=self.registration.duet_id.value,
            record=record,
        )
        inputs = self.service.builds.inspection_inputs_for_receipt(
            owned["spec"]["build_receipt_ref"]["artifact_id"]
        )
        _, recording = load_recording(
            self.service.artifacts,
            self.service.runs,
            reference,
            inputs.build_request.frozen_workflow.duet_id.value,
        )
        return {"recording_ref": reference, **recording_summary(recording)}
